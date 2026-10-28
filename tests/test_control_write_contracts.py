"""Actual configuration entities preserve write ordering and error boundaries."""

import asyncio
import json
import unittest
from datetime import time
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

from tests.support import FakeHass, build_coordinator, install_control_stubs, load_package_module

install_control_stubs()
platforms = {name: load_package_module(name) for name in ("number", "switch", "select", "time")}
configuration = load_package_module("configuration.values")
results = load_package_module("runtime.write_results")
FIXTURE = Path(__file__).parent / "fixtures/control_write_contracts.json"
ENTITIES = {
    "max_current": ("number", "MaxCurrentNumber", "G_MaxCurrent", 20),
    "load_limit": ("number", "LoadBalancingLimitNumber", "G_ExternalLimitPower", 12),
    "price": ("number", "ElectricityPriceNumber", "G_TimeSharingPrice", 0.3),
    "load_enable": ("switch", "LoadBalancingEnableSwitch", "G_ExternalLimitPowerEnable", True),
    "lcd": ("switch", "LcdDisplaySwitch", "G_LCDCloseEnable", True),
    "mode": ("select", "WorkingModeSelect", "G_OffPeakEnable", "off_peak"),
    "schedule": ("time", "AutoChargeStartTime", "G_AutoChargeTime", time(2)),
}
FIELDS = (
    "max_current",
    "external_limit_power",
    "electricity_price",
    "external_limit_power_enable",
    "lcd_close_enable",
    "auto_charge_start_time",
    "auto_charge_stop_time",
    "auto_charge_start_time_pending",
    "auto_charge_stop_time_pending",
)


def safe(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, time):
        return value.isoformat()
    return value


async def capture(name, outcome):
    c = build_coordinator()
    c.hass = FakeHass(asyncio.get_running_loop(), config=SimpleNamespace(currency="EUR"))
    c.now = lambda: "2026-10-28T10:00:00Z"
    c.max_current, c.external_limit_power, c.electricity_price = 16, 10, 0.25
    c.external_limit_power_enable, c.lcd_close_enable = False, "Enable"
    c.auto_charge_start_time = c.auto_charge_start_time_pending = time(1)
    c.auto_charge_stop_time = c.auto_charge_stop_time_pending = time(6)
    raw = {
        "G_WorkingMode": "Fast",
        "G_SolarMode": "0",
        "G_MaxCurrent": "16",
        "G_ExternalLimitPower": "10",
        "G_ExternalLimitPowerEnable": "0",
        "G_LCDCloseEnable": "Enable",
        "G_TimeSharingPrice": "time1=00:00-23:59&price1=0.25",
        "G_AutoChargeTime": "01:00-06:00",
    }
    c.configuration_values = {
        key: configuration.configuration_value_from_item(
            {"key": key, "value": value, "readonly": False}
        )
        for key, value in raw.items()
    }
    trace = []

    def state():
        return [safe(getattr(c, key)) for key in FIELDS]

    c.async_set_updated_data = lambda _: trace.append(["notify", state()])

    def refresh(*, delay=20.0):
        trace.append(["refresh", delay])
        future = asyncio.get_running_loop().create_future()
        future.set_result(None)
        return future

    c.schedule_configuration_refresh = refresh
    c.write_queue.min_write_interval = c.write_queue.poll_pause_after_write = 0
    platform, class_name, key, value = ENTITIES[name]
    entity = getattr(platforms[platform], class_name)(c, SimpleNamespace(entry_id="entry-test"))
    entity.hass = c.hass
    entity.on_state_write = lambda: trace.append(["entity", safe(entity.current_option)])
    original_update = c.update_configuration_value

    def update(key, value):
        trace.append(["reported", key, value])
        original_update(key, value)

    c.update_configuration_value = update

    async def change(key, raw_value):
        trace.append(["wire", key, raw_value])
        if outcome == "uncertain":
            raise results.ChargerRequestOutcomeUncertain("lost connection")
        if outcome == "unexpected":
            raise RuntimeError("test failure")
        if outcome == "superseded":
            replacement = {
                "max_current": "17",
                "load_limit": "11",
                "price": "time1=00:00-23:59&price1=0.40",
                "load_enable": "0",
                "lcd": "Enable",
                "mode": "Fast",
                "schedule": "03:00-07:00",
            }[name]
            if name == "mode":
                entity._pending_option, entity._pending_intent = "fast", entity._intent_sequence + 1
            if name == "max_current":
                c.max_current = 17
            if name == "load_limit":
                c.external_limit_power = 11
            if name == "price":
                c.electricity_price = 0.4
            c.begin_configuration_write(key, replacement)
        return (
            "Rejected"
            if outcome == "rejected"
            else "RebootRequired"
            if outcome == "reboot"
            else "Accepted"
        )

    c.runtime_data["charge_point"] = SimpleNamespace(change_configuration=change)
    if outcome == "cancelled":
        enqueue = c.queue_write

        async def cancel_before_execution(*args, **kwargs):
            handle = await enqueue(*args, **kwargs)
            c.cancel_queued_writes(dedupe_key=kwargs["dedupe_key"], reason="contract_cancelled")
            return handle

        c.queue_write = cancel_before_execution
    callbacks = []
    c.schedule_auto_charge_schedule_write = callbacks.append
    error = None
    try:
        if platform == "number":
            await entity.async_set_native_value(value)
        elif platform == "switch":
            await entity.async_turn_on()
        elif platform == "select":
            await entity.async_select_option(value)
        else:
            await entity.async_set_value(value)
            await callbacks[-1]()
            await c.write_queue.idle.wait()
        await asyncio.sleep(0)
    except Exception as exc:
        error = getattr(exc, "translation_key", None) or type(exc).__name__
    finally:
        await c.write_queue.async_shutdown()
        if getattr(entity, "_readback_task", None) is not None:
            await entity._readback_task
    result = {
        "trace": trace,
        "state": state(),
        "error": error,
        "attributes": entity.extra_state_attributes,
        "writes": {
            key: {
                "status": item.status.value,
                "generation": item.generation,
                "raw": item.requested_raw_value,
            }
            for key, item in c.configuration_writes.items()
        },
        "reported": {key: item.raw_value for key, item in c.configuration_values.items()},
    }
    return result


class ControlWriteContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_control_write_contracts(self):
        expected = json.loads(FIXTURE.read_text())
        for name in ENTITIES:
            for outcome in (
                "accepted",
                "reboot",
                "rejected",
                "uncertain",
                "unexpected",
                "superseded",
                "cancelled",
            ):
                with self.subTest(entity=name, outcome=outcome):
                    self.assertEqual(await capture(name, outcome), expected[name + ":" + outcome])
