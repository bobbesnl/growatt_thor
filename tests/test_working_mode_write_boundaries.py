"""Working mode rules that the outcome fixture does not reach.

Working modes write different configuration keys, so the entity intent token
and one shared dedupe key protect a selection where per-key generations
cannot: across keys, and while the external meter's health changes.
"""

import asyncio
import unittest
from types import SimpleNamespace

from tests.support import FakeHass, build_coordinator, install_control_stubs, load_package_module

install_control_stubs()
select = load_package_module("select")
configuration = load_package_module("configuration.values")
results = load_package_module("runtime.write_results")


class WorkingModeWriteBoundaryTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.coordinator = c = build_coordinator()
        c.hass = FakeHass(asyncio.get_running_loop())
        c.now = lambda: "2026-11-03T10:00:00Z"
        c.write_queue.min_write_interval = c.write_queue.poll_pause_after_write = 0
        c.configuration_values = {
            key: configuration.configuration_value_from_item(
                {"key": key, "value": value, "readonly": False}
            )
            for key, value in {"G_WorkingMode": "Fast", "G_SolarMode": "1&0"}.items()
        }
        c.external_meter = SimpleNamespace(ready_for_pv=True, health="healthy")
        self.refreshes = []
        c.schedule_configuration_refresh = self.refresh
        self.reported = []
        update = c.update_configuration_value

        def record_update(key, value):
            self.reported.append(key)
            update(key, value)

        c.update_configuration_value = record_update
        self.wire = []
        self.on_send = None
        c.runtime_data["charge_point"] = SimpleNamespace(change_configuration=self.change)
        self.entity = select.WorkingModeSelect(c, SimpleNamespace(entry_id="entry-test"))
        self.entity.hass = c.hass

    async def asyncTearDown(self):
        await self.coordinator.write_queue.async_shutdown()
        if self.entity._readback_task is not None:
            await self.entity._readback_task

    def refresh(self, **kwargs):
        self.refreshes.append(kwargs)
        future = asyncio.get_running_loop().create_future()
        future.set_result(None)
        return future

    async def change(self, key, raw_value):
        self.wire.append((key, raw_value))
        if self.on_send is not None:
            self.on_send()
        return "Accepted"

    async def test_newer_selection_on_another_key_wins_over_older_acceptance(self):
        entity = self.entity

        def newer_selection():
            # A newer mode selection may target another configuration key, so
            # the per-key generation of the older write is still current.
            entity._pending_option = "off_peak"
            entity._pending_intent = entity._intent_sequence + 1

        self.on_send = newer_selection

        await entity.async_select_option("pv_linkage")

        self.assertEqual(self.wire, [("G_SolarMode", "1&1")])
        self.assertEqual(self.reported, [])
        self.assertEqual(entity._pending_option, "off_peak")

    async def test_meter_health_is_rechecked_before_sending_pv_linkage(self):
        c = self.coordinator
        enqueue = c.queue_write

        async def meter_fails_while_queued(*args, **kwargs):
            c.external_meter.ready_for_pv = False
            return await enqueue(*args, **kwargs)

        c.queue_write = meter_fails_while_queued

        with self.assertRaises(Exception) as raised:
            await self.entity.async_select_option("pv_linkage")

        self.assertEqual(raised.exception.translation_key, "command_not_executed")
        self.assertEqual(self.wire, [])
        self.assertEqual(c.configuration_writes["G_SolarMode"].status.value, "skipped")
        self.assertIsNone(self.entity._pending_option)

    async def test_newer_mode_replaces_unsent_mode_on_another_key(self):
        c = self.coordinator
        release = asyncio.Event()
        blocker = asyncio.get_running_loop().create_future()

        async def hold():
            # Keep both mode writes queued behind an unrelated command.
            blocker.set_result(None)
            await release.wait()
            return results.ChargerWriteResult.success()

        await c.queue_write(hold, command_name="hold")
        await blocker
        older = asyncio.create_task(self.entity.async_select_option("off_peak"))
        await asyncio.sleep(0)
        newer = asyncio.create_task(self.entity.async_select_option("pv_linkage"))
        await asyncio.sleep(0)
        release.set()

        with self.assertRaises(Exception) as raised:
            await older
        await newer

        self.assertEqual(raised.exception.translation_key, "command_not_executed")
        self.assertEqual(self.wire, [("G_SolarMode", "1&1")])


if __name__ == "__main__":
    unittest.main()
