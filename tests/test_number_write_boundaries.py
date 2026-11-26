"""Number write rules that the outcome fixture does not reach.

``control_write_contracts.json`` drives each outcome from the wire. These cases
cover the queued revalidation, generation-owned rollback and the error boundary
that also encloses acceptance handling.
"""

import asyncio
import unittest
from types import SimpleNamespace

from tests.support import FakeHass, build_coordinator, install_control_stubs, load_package_module

install_control_stubs()
number = load_package_module("number")
configuration = load_package_module("configuration.values")


class NumberWriteBoundaryTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.coordinator = c = build_coordinator()
        c.hass = FakeHass(asyncio.get_running_loop(), config=SimpleNamespace(currency="EUR"))
        c.now = lambda: "2026-11-03T10:00:00Z"
        c.write_queue.min_write_interval = c.write_queue.poll_pause_after_write = 0
        c.max_current = 16
        c.configuration_values = {
            "G_MaxCurrent": configuration.configuration_value_from_item(
                {"key": "G_MaxCurrent", "value": "16", "readonly": False}
            )
        }
        c.schedule_configuration_refresh = lambda **_kwargs: None
        self.wire = []
        self.on_send = None
        self.result = "Accepted"
        c.runtime_data["charge_point"] = SimpleNamespace(change_configuration=self.change)
        self.entity = number.MaxCurrentNumber(c, SimpleNamespace(entry_id="entry-test"))
        self.entity.hass = c.hass

    async def asyncTearDown(self):
        await self.coordinator.write_queue.async_shutdown()

    async def change(self, key, raw_value):
        self.wire.append((key, raw_value))
        if self.on_send is not None:
            self.on_send()
        return self.result

    async def set_value(self, value):
        try:
            await self.entity.async_set_native_value(value)
        except Exception as exc:
            return getattr(exc, "translation_key", type(exc).__name__)
        return None

    def write_status(self):
        return self.coordinator.configuration_writes["G_MaxCurrent"].status.value

    async def test_lowered_model_limit_skips_queued_current_and_restores_reported_value(self):
        c = self.coordinator
        enqueue = c.queue_write

        async def report_smaller_model_while_queued(*args, **kwargs):
            c.boot_notification = {"request": {"charge_point_model": "THOR11AS"}}
            return await enqueue(*args, **kwargs)

        c.queue_write = report_smaller_model_while_queued

        error = await self.set_value(20)

        self.assertEqual(self.wire, [])
        self.assertEqual(self.write_status(), "skipped")
        self.assertEqual(error, "command_not_executed")
        self.assertEqual(c.max_current, 16)

    async def test_superseded_rejection_keeps_the_newer_optimistic_value(self):
        c = self.coordinator
        self.result = "Rejected"

        def newer_intent():
            c.max_current = 18
            c.begin_configuration_write("G_MaxCurrent", "18")

        self.on_send = newer_intent

        await self.set_value(20)

        self.assertEqual(self.wire, [("G_MaxCurrent", "20")])
        self.assertEqual(c.max_current, 18)

    async def test_failure_after_acknowledgement_restores_and_fails_terminally(self):
        c = self.coordinator

        def broken_update(key, value):
            raise RuntimeError("accepted-state failure")

        c.update_configuration_value = broken_update

        with self.assertLogs(number._LOGGER, "ERROR"):
            error = await self.set_value(20)

        self.assertEqual(error, "command_failed")
        self.assertEqual(c.max_current, 16)


if __name__ == "__main__":
    unittest.main()
