"""Setup, unload, reload, flows and services against a real Home Assistant."""

from __future__ import annotations

import socket

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growatt_thor.const import (
    CONF_BIND_ADDRESS,
    CONF_LOCATION,
    CONF_POLL_INTERVAL,
    CONF_PORT,
    DOMAIN,
)

from .conftest import free_port, port_is_free

PLATFORMS = {"button", "number", "select", "sensor", "switch", "time"}


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    port = free_port()
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_PORT: port,
            CONF_BIND_ADDRESS: "127.0.0.1",
            CONF_LOCATION: "Garage",
            CONF_POLL_INTERVAL: 30,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Growatt THOR EV Charger"
    assert result["data"][CONF_PORT] == port
    assert result["data"][CONF_BIND_ADDRESS] == "127.0.0.1"
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_user_flow_rejects_a_port_used_by_another_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_PORT: config_entry.data[CONF_PORT],
            CONF_LOCATION: "",
            CONF_POLL_INTERVAL: 30,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_PORT: "port_already_configured"}


async def test_setup_creates_device_and_entities_on_every_platform(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert not port_is_free(config_entry.data[CONF_PORT])
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), config_entry.entry_id)
    assert devices
    entities = er.async_entries_for_config_entry(er.async_get(hass), config_entry.entry_id)
    assert {entity.domain for entity in entities} >= PLATFORMS
    assert all(entity.unique_id for entity in entities)
    assert hass.states.get(_entity_id(entities, "button")) is not None


async def test_unload_releases_the_port_and_reload_binds_it_again(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)
    port = config_entry.data[CONF_PORT]

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED
    assert port_is_free(port)

    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    assert not port_is_free(port)

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_retries_when_the_port_is_taken(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.bind(("127.0.0.1", config_entry.data[CONF_PORT]))
        blocker.listen()
        config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_options_flow_updates_general_settings(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "general"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "general"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_BIND_ADDRESS: "127.0.0.1", CONF_POLL_INTERVAL: 45, CONF_LOCATION: "Carport"},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.data[CONF_POLL_INTERVAL] == 45
    assert config_entry.data[CONF_LOCATION] == "Carport"
    assert config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(config_entry.entry_id)


async def test_services_are_registered_and_report_a_missing_charger(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)

    services = hass.services.async_services_for_domain(DOMAIN)
    assert {
        "refresh",
        "export_sessions",
        "charging_target_status",
        "start_charging_target",
        "cancel_scheduled_charging_target",
    } <= set(services)

    with pytest.raises(HomeAssistantError) as raised:
        await hass.services.async_call(
            DOMAIN,
            "refresh",
            {"config_entry_id": config_entry.entry_id},
            blocking=True,
        )
    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key

    status = await hass.services.async_call(
        DOMAIN,
        "charging_target_status",
        {"entry_id": config_entry.entry_id},
        blocking=True,
        return_response=True,
    )
    assert isinstance(status, dict)

    assert await hass.config_entries.async_unload(config_entry.entry_id)


def _entity_id(entities: list[er.RegistryEntry], domain: str) -> str:
    return next(entity.entity_id for entity in entities if entity.domain == domain)
