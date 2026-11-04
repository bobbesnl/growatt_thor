"""End-to-end scenarios: Home Assistant, the OCPP server and a simulated charger.

Each scenario connects a simulated charge point over a real WebSocket to the
server of a loaded config entry and drives it through HA buttons, as a user
or automation would.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest
import websockets
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from ocpp.v16.enums import RemoteStartStopStatus
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growatt_thor.const import CONF_PORT, DOMAIN

from .simulator import SimulatedThor, connected_thor

TIMEOUT = 10


async def _wait_for(condition: Callable[[], bool], what: str) -> None:
    try:
        async with asyncio.timeout(TIMEOUT):
            while not condition():
                await asyncio.sleep(0.05)
    except TimeoutError:
        pytest.fail(f"Timed out waiting until {what}")


def _entity_id(hass: HomeAssistant, entry: MockConfigEntry, platform: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id is not None, key
    return entity_id


def _state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state.state


def _number(hass: HomeAssistant, entity_id: str) -> float | None:
    try:
        return float(_state(hass, entity_id))
    except ValueError:
        return None


async def _press(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)


@pytest.fixture
async def loaded_entry(hass: HomeAssistant, config_entry: MockConfigEntry) -> MockConfigEntry:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    yield config_entry
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


async def _connect_ready(hass: HomeAssistant, entry: MockConfigEntry, thor: SimulatedThor) -> str:
    """Boot the simulated charger with a plugged-in car; return the Start button."""
    boot = await thor.boot()
    assert boot.status == "Accepted"
    await thor.status("Preparing")
    start = _entity_id(hass, entry, "button", "start_charging")
    await _wait_for(lambda: _state(hass, start) != STATE_UNAVAILABLE, "Start becomes available")
    return start


async def _start_session(hass: HomeAssistant, thor: SimulatedThor, start_button: str) -> int:
    """Press Start and answer it like THOR: StartTransaction, then Charging."""
    await _press(hass, start_button)
    remote_start = thor.remote_starts.get_nowait()
    assert remote_start["connector_id"] == 1

    started = await thor.start_transaction(remote_start["id_tag"], meter_start=1000)
    # The integration's one-shot Remote Start grant authorizes its own id tag.
    assert started.id_tag_info["status"] == "Accepted"
    assert started.transaction_id > 0
    await thor.status("Charging")
    return int(started.transaction_id)


async def test_remote_start_meter_values_and_remote_stop(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    async with connected_thor(loaded_entry.data[CONF_PORT]) as thor:
        start = await _connect_ready(hass, loaded_entry, thor)
        firmware = _entity_id(hass, loaded_entry, "sensor", "firmware_version")
        await _wait_for(lambda: _state(hass, firmware) == "THOR_11AS-SIM", "firmware reported")

        plugged = _entity_id(hass, loaded_entry, "binary_sensor", "vehicle_connected")
        charging = _entity_id(hass, loaded_entry, "binary_sensor", "charging")
        connection = _entity_id(hass, loaded_entry, "binary_sensor", "charger_connected")
        assert _state(hass, connection) == "on"
        await _wait_for(lambda: _state(hass, plugged) == "on", "vehicle reported plugged in")
        assert _state(hass, charging) == "off"

        transaction_id = await _start_session(hass, thor, start)
        await _wait_for(lambda: _state(hass, charging) == "on", "charging reported")

        power = _entity_id(hass, loaded_entry, "sensor", "charging_power")
        await thor.meter_values(transaction_id, power_w=7200, energy_wh=1500)
        await _wait_for(lambda: _number(hass, power) == 7200, "charging power reported")

        await _press(hass, _entity_id(hass, loaded_entry, "button", "stop_charging"))
        assert thor.remote_stops.get_nowait() == {"transaction_id": transaction_id}

        await thor.stop_transaction(transaction_id, meter_stop=2500, reason="Remote")
        await thor.status("Finishing")
        await _wait_for(lambda: _number(hass, power) == 0, "live power reset after stop")


async def test_rejected_remote_start_is_reported_to_the_caller(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    async with connected_thor(loaded_entry.data[CONF_PORT]) as thor:
        start = await _connect_ready(hass, loaded_entry, thor)
        thor.remote_start_status = RemoteStartStopStatus.rejected

        with pytest.raises(HomeAssistantError) as raised:
            await _press(hass, start)

        assert raised.value.translation_domain == DOMAIN
        assert thor.remote_starts.qsize() == 1


async def test_reconnect_during_a_transaction_keeps_it_stoppable(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    port = loaded_entry.data[CONF_PORT]
    stop = _entity_id(hass, loaded_entry, "button", "stop_charging")
    async with connected_thor(port) as thor:
        start = await _connect_ready(hass, loaded_entry, thor)
        transaction_id = await _start_session(hass, thor, start)

    # The socket dropped mid-transaction; the charger keeps charging.
    await _wait_for(lambda: _state(hass, start) == STATE_UNAVAILABLE, "disconnect observed")

    async with connected_thor(port) as thor:
        await thor.boot()
        await thor.status("Charging")
        await thor.meter_values(transaction_id, power_w=3600, energy_wh=1800)

        await _press(hass, stop)
        # The Stop is bound to the transaction from before the reconnect and
        # is sent on the new socket.
        assert thor.remote_stops.get_nowait() == {"transaction_id": transaction_id}
        await thor.stop_transaction(transaction_id, meter_stop=2600, reason="Remote")


async def test_a_different_charger_cannot_take_over_the_entry(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    port = loaded_entry.data[CONF_PORT]
    async with connected_thor(port, "THOR-OWNER") as owner:
        await _connect_ready(hass, loaded_entry, owner)

        intruder = await websockets.connect(
            f"ws://127.0.0.1:{port}/ocpp/ws/THOR-OTHER",
            subprotocols=["ocpp1.6"],
            ping_interval=None,
        )
        with pytest.raises(websockets.exceptions.ConnectionClosed) as closed:
            await asyncio.wait_for(intruder.recv(), TIMEOUT)
        assert closed.value.rcvd is not None
        assert closed.value.rcvd.code == 1008

        charge_point_id = _entity_id(hass, loaded_entry, "sensor", "charge_point_id")
        assert _state(hass, charge_point_id) == "THOR-OWNER"
