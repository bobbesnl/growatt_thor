"""Auto Charge schedule rules that the outcome fixture does not reach.

The two time entities form one queued schedule snapshot. When a newer snapshot
replaces an unsent older one, the older write must not restore the pending
fields over the newer intent.
"""

import asyncio
import unittest
from datetime import time
from types import SimpleNamespace

from tests.support import FakeHass, build_coordinator, install_control_stubs, load_package_module

install_control_stubs()
time_platform = load_package_module("time")
configuration = load_package_module("configuration.values")
results = load_package_module("runtime.write_results")


class AutoChargeWriteBoundaryTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.coordinator = c = build_coordinator()
        c.hass = FakeHass(asyncio.get_running_loop())
        c.now = lambda: "2026-11-03T10:00:00Z"
        c.write_queue.min_write_interval = c.write_queue.poll_pause_after_write = 0
        c.auto_charge_start_time = c.auto_charge_start_time_pending = time(1)
        c.auto_charge_stop_time = c.auto_charge_stop_time_pending = time(6)
        reported = {
            "G_WorkingMode": "Fast",
            "G_SolarMode": "0",
            "G_AutoChargeTime": "01:00-06:00",
        }
        c.configuration_values = {
            key: configuration.configuration_value_from_item(
                {"key": key, "value": value, "readonly": False}
            )
            for key, value in reported.items()
        }
        c.schedule_configuration_refresh = lambda **_kwargs: None
        self.wire = []

        async def change(key, raw_value):
            self.wire.append((key, raw_value))
            return "Accepted"

        c.runtime_data["charge_point"] = SimpleNamespace(change_configuration=change)
        self.callbacks = []
        c.schedule_auto_charge_schedule_write = self.callbacks.append
        self.entity = time_platform.AutoChargeStartTime(c, SimpleNamespace(entry_id="entry-test"))
        self.entity.hass = c.hass

    async def asyncTearDown(self):
        await self.coordinator.write_queue.async_shutdown()

    async def test_replaced_unsent_schedule_keeps_the_newer_pending_fields(self):
        c = self.coordinator
        release = asyncio.Event()
        started = asyncio.get_running_loop().create_future()

        async def hold():
            # Keep both schedule snapshots queued behind an unrelated command.
            started.set_result(None)
            await release.wait()
            return results.ChargerWriteResult.success()

        await c.queue_write(hold, command_name="hold")
        await started
        await self.entity.async_set_value(time(2))
        await self.callbacks[-1]()
        await self.entity.async_set_value(time(3))
        await self.callbacks[-1]()

        self.assertEqual(c.auto_charge_start_time_pending, time(3))
        release.set()
        await c.write_queue.idle.wait()

        self.assertEqual(self.wire, [("G_AutoChargeTime", "03:00-06:00")])
        self.assertEqual(c.auto_charge_start_time_pending, time(3))
        self.assertEqual(c.auto_charge_start_time, time(3))


if __name__ == "__main__":
    unittest.main()
