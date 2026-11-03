"""Configuration entities refuse blocked actions and skip unchanged values.

``control_write_contracts.json`` covers what happens after a value reaches the
wire. These cases cover the paths that must never reach it: a blocked action,
a block that appears while the write waits in the queue, and a request for the
value that is already shown.
"""

import asyncio
import unittest
from datetime import time
from types import SimpleNamespace

from tests.support import FakeHass, build_coordinator
from tests.test_control_write_contracts import ENTITIES, configuration, platforms

REPORTED = {
    "G_WorkingMode": "Fast",
    "G_SolarMode": "0",
    "G_MaxCurrent": "16",
    "G_ExternalLimitPower": "10",
    "G_ExternalLimitPowerEnable": "0",
    "G_LCDCloseEnable": "Enable",
    "G_TimeSharingPrice": "time1=00:00-23:59&price1=0.25",
    "G_AutoChargeTime": "01:00-06:00",
    "G_ChargerMode": "1",
    "G_FullContinueChargeEnable": "Disable",
}
# The value each entity already shows for REPORTED.
UNCHANGED = {
    "max_current": 16,
    "load_limit": 10,
    "price": 0.25,
    "load_enable": False,
    "lcd": False,
    "mode": "fast",
    "warm_up": False,
    "authorization": "home_assistant_rfid",
}
CHANGED = ("max_current", "load_limit", "price", "load_enable", "lcd", "mode", "warm_up")


async def request(entity, platform, value, callbacks):
    if platform == "number":
        await entity.async_set_native_value(value)
    elif platform == "switch":
        await (entity.async_turn_on() if value else entity.async_turn_off())
    elif platform == "select":
        await entity.async_select_option(value)
    else:
        await entity.async_set_value(value)
        await callbacks[-1]()


class ControlWriteGuardTest(unittest.IsolatedAsyncioTestCase):
    async def build(self, name):
        c = build_coordinator()
        c.hass = FakeHass(asyncio.get_running_loop(), config=SimpleNamespace(currency="EUR"))
        c.now = lambda: "2026-11-03T10:00:00Z"
        c.write_queue.min_write_interval = c.write_queue.poll_pause_after_write = 0
        c.max_current, c.external_limit_power, c.electricity_price = 16, 10, 0.25
        c.external_limit_power_enable, c.lcd_close_enable = False, "Enable"
        c.auto_charge_start_time = c.auto_charge_start_time_pending = time(1)
        c.auto_charge_stop_time = c.auto_charge_stop_time_pending = time(6)
        c.status = "Available"
        c.configuration_values = {
            key: configuration.configuration_value_from_item(
                {"key": key, "value": value, "readonly": False}
            )
            for key, value in REPORTED.items()
        }
        c.schedule_configuration_refresh = lambda **_kwargs: None
        self.wire = []

        async def change(key, raw_value):
            self.wire.append((key, raw_value))
            return "Accepted"

        c.runtime_data["charge_point"] = SimpleNamespace(change_configuration=change)
        self.callbacks = []
        c.schedule_auto_charge_schedule_write = self.callbacks.append
        platform, class_name, _key, value = ENTITIES[name]
        entity = getattr(platforms[platform], class_name)(c, SimpleNamespace(entry_id="entry-test"))
        entity.hass = c.hass
        self.addAsyncCleanup(c.write_queue.async_shutdown)
        return c, entity, platform, value

    async def test_blocked_action_raises_before_recording_an_intent(self):
        for name in (*CHANGED, "schedule"):
            with self.subTest(entity=name):
                c, entity, platform, value = await self.build(name)
                c.status = "Faulted"

                with self.assertRaises(Exception) as raised:
                    await request(entity, platform, value, self.callbacks)

                self.assertEqual(raised.exception.translation_key, "charger_faulted")
                self.assertEqual(c.configuration_writes, {})
                self.assertEqual(self.wire, [])

    async def test_block_while_queued_skips_without_sending(self):
        for name in (*CHANGED, "schedule"):
            with self.subTest(entity=name):
                c, entity, platform, value = await self.build(name)
                enqueue = c.queue_write

                async def fault_while_queued(*args, _c=c, _enqueue=enqueue, **kwargs):
                    _c.status = "Faulted"
                    return await _enqueue(*args, **kwargs)

                c.queue_write = fault_while_queued
                try:
                    await request(entity, platform, value, self.callbacks)
                except Exception as exc:
                    self.assertEqual(exc.translation_key, "command_not_executed")
                await c.write_queue.idle.wait()

                self.assertEqual(self.wire, [])
                self.assertEqual(
                    [write.status.value for write in c.configuration_writes.values()],
                    ["skipped"],
                )

    async def test_unchanged_value_records_no_intent(self):
        for name, value in UNCHANGED.items():
            with self.subTest(entity=name):
                c, entity, platform, _value = await self.build(name)

                await request(entity, platform, value, self.callbacks)

                self.assertEqual(c.configuration_writes, {})
                self.assertEqual(self.wire, [])


if __name__ == "__main__":
    unittest.main()
