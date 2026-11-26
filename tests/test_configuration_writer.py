"""ConfigurationWriter owns the order of the shared configuration write steps."""

import asyncio
import unittest
from types import SimpleNamespace

from tests.support import (
    FakeHass,
    HomeAssistantError,
    build_coordinator,
    install_control_stubs,
    load_package_module,
)

install_control_stubs()
writer_module = load_package_module("configuration.writer")
results = load_package_module("runtime.write_results")
writes = load_package_module("configuration.writes")

KEY = "G_Test"


class RecordingPolicy(writer_module.WritePolicy):
    label = "Test control"

    def __init__(self, owner, trace):
        super().__init__(owner)
        self.trace = trace
        self.block_reason = None
        self.queued_reason = None
        self.unchanged = False
        self.unexpected_result = None

    def encode(self, value):
        return KEY, f"raw-{value}"

    def request_block_reason(self):
        return self.block_reason

    def queued_block_reason(self, write):
        return self.queued_reason

    def is_unchanged(self, value):
        return self.unchanged

    def apply_optimistic(self, value):
        self.trace.append(["optimistic", value])
        return "previous"

    def on_skipped(self, write, reason):
        self.trace.append(["skipped", reason])

    def on_unsent(self, write):
        self.trace.append(["unsent", write.value, write.previous])

    def apply_accepted(self, write):
        self.trace.append(["accepted", write.value])
        super().apply_accepted(write)

    def on_rejected(self, write, result):
        self.trace.append(["rejected", write.previous])

    def on_unexpected(self, write, exc):
        self.trace.append(["unexpected", type(exc).__name__])
        return self.unexpected_result


class ConfigurationWriterTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.coordinator = c = build_coordinator()
        c.hass = FakeHass(asyncio.get_running_loop())
        c.now = lambda: "2026-11-03T10:00:00Z"
        c.write_queue.min_write_interval = c.write_queue.poll_pause_after_write = 0
        self.trace = []
        c.async_set_updated_data = lambda _: None

        def refresh(**kwargs):
            self.trace.append(["refresh", kwargs])

        def update(key, value):
            self.trace.append(["reported", key, value])

        c.schedule_configuration_refresh = refresh
        c.update_configuration_value = update
        self.result = "Accepted"
        self.error = None
        c.runtime_data["charge_point"] = SimpleNamespace(change_configuration=self.change)
        self.policy = RecordingPolicy(c, self.trace)
        self.writer = writer_module.ConfigurationWriter(c, self.policy)

    async def asyncTearDown(self):
        await self.coordinator.write_queue.async_shutdown()

    async def change(self, key, raw_value):
        self.trace.append(["wire", key, raw_value])
        if self.error is not None:
            raise self.error
        return self.result

    async def request(self, value=1):
        """Run the full action flow and return the terminal queue result."""
        handles = []
        enqueue = self.coordinator.queue_write

        async def recording_queue_write(*args, **kwargs):
            handles.append(await enqueue(*args, **kwargs))
            return handles[-1]

        self.coordinator.queue_write = recording_queue_write
        try:
            await self.writer.async_request(value)
        except Exception:
            if not handles:
                raise
        finally:
            self.coordinator.queue_write = enqueue
        return await handles[-1].async_wait(timeout=5) if handles else None

    def write_status(self):
        return self.coordinator.configuration_writes[KEY].status

    async def test_accepted_applies_state_then_reads_back(self):
        result = await self.request()

        self.assertEqual(result.reason, None)
        self.assertEqual(
            self.trace,
            [
                ["optimistic", 1],
                ["wire", KEY, "raw-1"],
                ["accepted", 1],
                ["reported", KEY, "raw-1"],
                ["refresh", {}],
            ],
        )
        self.assertEqual(self.write_status(), writes.ConfigurationWriteStatus.AWAITING_READBACK)

    async def test_refresh_in_accept_skips_second_readback_for_current_outcome(self):
        self.policy.refreshes_on_apply = True

        await self.request()

        self.assertNotIn(["refresh", {}], self.trace)

    async def test_superseded_accept_reads_back_without_applying_state(self):
        self.policy.refreshes_on_apply = True

        async def change(key, raw_value):
            self.coordinator.begin_configuration_write(KEY, "raw-newer")
            return "Accepted"

        self.coordinator.runtime_data["charge_point"].change_configuration = change
        await self.request()

        self.assertEqual(self.trace, [["optimistic", 1], ["refresh", {}]])

    async def test_rejected_calls_policy_and_raises_public_error(self):
        self.result = "Rejected"

        result = await self.request()

        self.assertEqual(result.reason, "charger_rejected")
        self.assertEqual(self.trace[-1], ["rejected", "previous"])
        self.assertEqual(self.write_status(), writes.ConfigurationWriteStatus.REJECTED)

    async def test_uncertain_marks_write_and_reads_back_immediately(self):
        self.error = results.ChargerRequestOutcomeUncertain("lost")

        await self.request()

        self.assertEqual(self.trace[-1], ["refresh", {"delay": 0}])
        self.assertEqual(self.write_status(), writes.ConfigurationWriteStatus.UNCERTAIN)

    async def test_unexpected_send_error_reaches_queue_unless_policy_handles_it(self):
        self.error = RuntimeError("boom")

        result = await self.request()
        self.assertEqual(self.trace[-1], ["unexpected", "RuntimeError"])
        self.assertEqual(result.reason, "unexpected_error")

        self.policy.unexpected_result = results.ChargerWriteResult.failed("policy_handled")
        result = await self.request(2)
        self.assertEqual(result.reason, "policy_handled")

    async def test_outcome_boundary_is_policy_choice(self):
        def explode(write):
            raise RuntimeError("apply")

        self.policy.apply_accepted = explode
        self.policy.unexpected_result = results.ChargerWriteResult.failed("policy_handled")

        result = await self.request()
        self.assertNotIn(["unexpected", "RuntimeError"], self.trace)
        self.assertEqual(result.reason, "unexpected_error")

        self.policy.guards_outcome = True
        result = await self.request(2)
        self.assertEqual(result.reason, "policy_handled")
        self.assertEqual(self.trace[-1], ["unexpected", "RuntimeError"])

    async def test_queued_block_marks_skipped_before_policy_hooks(self):
        self.policy.queued_reason = "charging_active"

        result = await self.request()

        self.assertEqual(result.reason, "charging_active")
        # The queue reports a skipped write as unsent as well.
        self.assertEqual(
            self.trace[-2:], [["skipped", "charging_active"], ["unsent", 1, "previous"]]
        )
        self.assertNotIn("wire", [step[0] for step in self.trace])
        self.assertEqual(self.write_status(), writes.ConfigurationWriteStatus.SKIPPED)

    async def test_request_guards_raise_before_any_intent_is_recorded(self):
        self.policy.block_reason = "charging_active"
        with self.assertRaises(HomeAssistantError):
            await self.request()

        self.policy.block_reason = None
        self.coordinator.runtime_data.pop("charge_point")
        with self.assertRaises(Exception) as raised:
            await self.request()

        self.assertEqual(raised.exception.translation_key, "charger_disconnected")
        self.assertEqual(self.trace, [])
        self.assertNotIn(KEY, self.coordinator.configuration_writes)

    async def test_unchanged_request_queues_nothing(self):
        self.policy.unchanged = True

        await self.request()

        self.assertEqual(self.trace, [])
        self.assertNotIn(KEY, self.coordinator.configuration_writes)

    async def test_replaced_write_reports_unsent_with_rollback_token(self):
        cp = self.coordinator.runtime_data["charge_point"]
        handle = await self.writer.async_enqueue(cp, 1, previous="first")
        self.coordinator.cancel_queued_writes(dedupe_key=KEY, reason="replaced")
        await handle.async_wait(timeout=5)

        self.assertIn(["unsent", 1, "first"], self.trace)
        self.assertNotIn("wire", [step[0] for step in self.trace])


if __name__ == "__main__":
    unittest.main()
