"""Tests for configuration write readback tracking."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
    / "configuration_writes.py"
)
SPEC = importlib.util.spec_from_file_location(
    "growatt_thor_configuration_writes_test_target",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
writes = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = writes
SPEC.loader.exec_module(writes)


class ConfigurationWriteTrackingTest(unittest.TestCase):
    """Keep OCPP acceptance distinct from confirmed charger state."""

    def test_generations_increase_independently_per_configuration_key(self):
        state = writes.begin_configuration_write(
            {},
            key="G_MaxCurrent",
            raw_value="13",
            requested_at="2026-09-15T10:00:00Z",
        )
        first_generation = state["G_MaxCurrent"].generation
        state = writes.begin_configuration_write(
            state,
            key="G_LCDCloseEnable",
            raw_value="Disable",
            requested_at="2026-09-15T10:00:01Z",
        )
        state = writes.begin_configuration_write(
            state,
            key="G_MaxCurrent",
            raw_value="17",
            requested_at="2026-09-15T10:00:02Z",
        )

        self.assertEqual(first_generation, 1)
        self.assertEqual(state["G_MaxCurrent"].generation, 2)
        self.assertEqual(state["G_LCDCloseEnable"].generation, 1)

    def test_superseded_acknowledgement_cannot_replace_newer_intent(self):
        state = writes.begin_configuration_write(
            {},
            key="G_MaxCurrent",
            raw_value="13",
            requested_at="2026-09-15T10:00:00Z",
        )
        old_generation = state["G_MaxCurrent"].generation
        state = writes.begin_configuration_write(
            state,
            key="G_MaxCurrent",
            raw_value="17",
            requested_at="2026-09-15T10:00:01Z",
        )
        new_generation = state["G_MaxCurrent"].generation

        after_old_ack = writes.acknowledge_configuration_write(
            state,
            key="G_MaxCurrent",
            generation=old_generation,
            accepted=True,
            result="Accepted",
        )

        self.assertEqual(
            after_old_ack["G_MaxCurrent"].status,
            writes.ConfigurationWriteStatus.PENDING,
        )
        self.assertEqual(
            after_old_ack["G_MaxCurrent"].requested_raw_value,
            "17",
        )
        self.assertEqual(
            [
                (outcome.generation, outcome.outcome, outcome.result)
                for outcome in after_old_ack[
                    "G_MaxCurrent"
                ].superseded_outcomes
            ],
            [(old_generation, "accepted", "Accepted")],
        )
        self.assertFalse(
            writes.configuration_write_is_current(
                after_old_ack,
                key="G_MaxCurrent",
                generation=old_generation,
            )
        )
        self.assertTrue(
            writes.configuration_write_is_current(
                after_old_ack,
                key="G_MaxCurrent",
                generation=new_generation,
            )
        )

    def test_superseded_failure_outcomes_cannot_rollback_newer_intent(self):
        state = writes.begin_configuration_write(
            {},
            key="G_LCDCloseEnable",
            raw_value="Disable",
            requested_at="2026-09-15T10:00:00Z",
        )
        old_generation = state["G_LCDCloseEnable"].generation
        state = writes.begin_configuration_write(
            state,
            key="G_LCDCloseEnable",
            raw_value="Enable",
            requested_at="2026-09-15T10:00:01Z",
        )

        after_old_reject = writes.acknowledge_configuration_write(
            state,
            key="G_LCDCloseEnable",
            generation=old_generation,
            accepted=False,
            result="Rejected",
        )
        after_old_uncertain = writes.mark_configuration_write(
            after_old_reject,
            key="G_LCDCloseEnable",
            generation=old_generation,
            status=writes.ConfigurationWriteStatus.UNCERTAIN,
            result="connection lost after send",
        )

        self.assertEqual(
            after_old_uncertain["G_LCDCloseEnable"].status,
            writes.ConfigurationWriteStatus.PENDING,
        )
        self.assertEqual(
            [
                outcome.outcome
                for outcome in after_old_uncertain[
                    "G_LCDCloseEnable"
                ].superseded_outcomes
            ],
            ["rejected", "uncertain"],
        )
        self.assertEqual(
            writes.pending_configuration_value(
                after_old_uncertain,
                "G_LCDCloseEnable",
            ),
            "Enable",
        )

    def test_readback_for_older_value_does_not_resolve_newer_generation(self):
        state = writes.begin_configuration_write(
            {},
            key="G_MaxCurrent",
            raw_value="13",
            requested_at="2026-09-15T10:00:00Z",
        )
        old_generation = state["G_MaxCurrent"].generation
        state = writes.acknowledge_configuration_write(
            state,
            key="G_MaxCurrent",
            generation=old_generation,
            accepted=True,
            result="Accepted",
        )
        state = writes.begin_configuration_write(
            state,
            key="G_MaxCurrent",
            raw_value="17",
            requested_at="2026-09-15T10:00:01Z",
        )
        new_generation = state["G_MaxCurrent"].generation

        state = writes.confirm_configuration_writes(
            state,
            {"G_MaxCurrent": "13.00"},
            readback_at="2026-09-15T10:00:02Z",
        )

        tracked = state["G_MaxCurrent"]
        self.assertEqual(tracked.generation, new_generation)
        self.assertEqual(tracked.status, writes.ConfigurationWriteStatus.PENDING)
        self.assertIsNone(tracked.reported_raw_value)

    def test_generation_is_exposed_for_support_diagnostics(self):
        state = writes.begin_configuration_write(
            {},
            key="G_MaxCurrent",
            raw_value="17",
            requested_at="2026-09-15T10:00:00Z",
        )

        serialized = writes.serialize_configuration_writes(state)

        self.assertEqual(serialized["G_MaxCurrent"]["generation"], 1)
        self.assertEqual(serialized["G_MaxCurrent"]["superseded_outcomes"], [])

    def test_superseded_diagnostics_keep_only_five_latest_outcomes(self):
        state = writes.begin_configuration_write(
            {},
            key="G_MaxCurrent",
            raw_value="13",
            requested_at="2026-09-15T10:00:00Z",
        )
        old_generation = state["G_MaxCurrent"].generation
        state = writes.begin_configuration_write(
            state,
            key="G_MaxCurrent",
            raw_value="17",
            requested_at="2026-09-15T10:00:01Z",
        )

        for index in range(7):
            state = writes.mark_configuration_write(
                state,
                key="G_MaxCurrent",
                generation=old_generation,
                status=writes.ConfigurationWriteStatus.UNCERTAIN,
                result=f"old outcome {index}",
            )

        serialized = writes.serialize_configuration_writes(state)
        outcomes = serialized["G_MaxCurrent"]["superseded_outcomes"]
        self.assertEqual(len(outcomes), 5)
        self.assertEqual(outcomes[0]["result"], "old outcome 2")
        self.assertEqual(outcomes[-1]["result"], "old outcome 6")

    def test_accepted_write_waits_for_matching_readback(self):
        state = writes.begin_configuration_write(
            {},
            key="G_SolarMode",
            raw_value="1&1",
            requested_at="2026-08-24T10:00:00Z",
        )
        generation = state["G_SolarMode"].generation
        state = writes.acknowledge_configuration_write(
            state,
            key="G_SolarMode",
            generation=generation,
            accepted=True,
            result="Accepted",
        )
        self.assertEqual(
            state["G_SolarMode"].status,
            writes.ConfigurationWriteStatus.AWAITING_READBACK,
        )

        state = writes.confirm_configuration_writes(
            state,
            {"G_SolarMode": "1&1"},
            readback_at="2026-08-24T10:00:20Z",
        )
        self.assertEqual(
            state["G_SolarMode"].status,
            writes.ConfigurationWriteStatus.CONFIRMED,
        )

    def test_different_readback_is_retained_as_mismatch(self):
        state = writes.begin_configuration_write(
            {},
            key="G_SolarMode",
            raw_value="1&1",
            requested_at="2026-08-24T10:00:00Z",
        )
        generation = state["G_SolarMode"].generation
        state = writes.acknowledge_configuration_write(
            state,
            key="G_SolarMode",
            generation=generation,
            accepted=True,
            result="Accepted",
        )
        state = writes.confirm_configuration_writes(
            state,
            {"G_SolarMode": "1&0"},
            readback_at="2026-08-24T10:00:20Z",
        )
        write = state["G_SolarMode"]
        self.assertEqual(
            write.status,
            writes.ConfigurationWriteStatus.MISMATCH,
        )
        self.assertEqual(write.reported_raw_value, "1&0")

    def test_rejected_write_is_not_changed_by_readback(self):
        state = writes.begin_configuration_write(
            {},
            key="G_SolarMode",
            raw_value="1&1",
            requested_at="2026-08-24T10:00:00Z",
        )
        generation = state["G_SolarMode"].generation
        state = writes.acknowledge_configuration_write(
            state,
            key="G_SolarMode",
            generation=generation,
            accepted=False,
            result="Rejected",
        )
        state = writes.confirm_configuration_writes(
            state,
            {"G_SolarMode": "1&1"},
            readback_at="2026-08-24T10:00:20Z",
        )
        self.assertEqual(
            state["G_SolarMode"].status,
            writes.ConfigurationWriteStatus.REJECTED,
        )

    def test_uncertain_write_is_resolved_by_reconnect_readback(self):
        state = writes.begin_configuration_write(
            {},
            key="G_MaxCurrent",
            raw_value="17",
            requested_at="2026-09-11T12:12:25Z",
        )
        generation = state["G_MaxCurrent"].generation
        state = writes.mark_configuration_write(
            state,
            key="G_MaxCurrent",
            generation=generation,
            status=writes.ConfigurationWriteStatus.UNCERTAIN,
            result="connection lost before acknowledgement",
        )

        state = writes.confirm_configuration_writes(
            state,
            {"G_MaxCurrent": "13.00"},
            readback_at="2026-09-11T12:13:09Z",
        )

        write = state["G_MaxCurrent"]
        self.assertEqual(write.status, writes.ConfigurationWriteStatus.MISMATCH)
        self.assertEqual(write.reported_raw_value, "13.00")

    def test_uncertain_write_can_be_confirmed_after_lost_acknowledgement(self):
        state = writes.begin_configuration_write(
            {},
            key="G_MaxCurrent",
            raw_value="17",
            requested_at="2026-09-11T12:12:25Z",
        )
        generation = state["G_MaxCurrent"].generation
        state = writes.mark_configuration_write(
            state,
            key="G_MaxCurrent",
            generation=generation,
            status=writes.ConfigurationWriteStatus.UNCERTAIN,
        )

        state = writes.confirm_configuration_writes(
            state,
            {"G_MaxCurrent": "17.00"},
            readback_at="2026-09-11T12:13:09Z",
        )

        self.assertEqual(
            state["G_MaxCurrent"].status,
            writes.ConfigurationWriteStatus.CONFIRMED,
        )

    def test_skipped_write_is_not_reclassified_by_readback(self):
        state = writes.begin_configuration_write(
            {},
            key="G_AutoChargeTime",
            raw_value="01:00-05:00",
            requested_at="2026-09-11T12:00:00Z",
        )
        generation = state["G_AutoChargeTime"].generation
        state = writes.mark_configuration_write(
            state,
            key="G_AutoChargeTime",
            generation=generation,
            status=writes.ConfigurationWriteStatus.SKIPPED,
            result="active_transaction",
        )

        state = writes.confirm_configuration_writes(
            state,
            {"G_AutoChargeTime": "01:00-05:00"},
            readback_at="2026-09-11T12:01:00Z",
        )

        self.assertEqual(
            state["G_AutoChargeTime"].status,
            writes.ConfigurationWriteStatus.SKIPPED,
        )

    def test_pending_value_is_visible_until_readback_resolves_it(self):
        """The LCD can show intent while a rate-limited write is in flight."""
        state = writes.begin_configuration_write(
            {},
            key="G_LCDCloseEnable",
            raw_value="Disable",
            requested_at="2026-09-11T12:00:00Z",
        )
        generation = state["G_LCDCloseEnable"].generation
        self.assertEqual(
            writes.pending_configuration_value(state, "G_LCDCloseEnable"),
            "Disable",
        )

        state = writes.acknowledge_configuration_write(
            state,
            key="G_LCDCloseEnable",
            generation=generation,
            accepted=True,
            result="Accepted",
        )
        self.assertEqual(
            writes.pending_configuration_value(state, "G_LCDCloseEnable"),
            "Disable",
        )

        state = writes.confirm_configuration_writes(
            state,
            {"G_LCDCloseEnable": "Disable"},
            readback_at="2026-09-11T12:01:00Z",
        )
        self.assertIsNone(
            writes.pending_configuration_value(state, "G_LCDCloseEnable")
        )

    def test_rejected_value_does_not_override_reported_lcd_state(self):
        state = writes.begin_configuration_write(
            {},
            key="G_LCDCloseEnable",
            raw_value="Enable",
            requested_at="2026-09-11T12:00:00Z",
        )
        generation = state["G_LCDCloseEnable"].generation
        state = writes.acknowledge_configuration_write(
            state,
            key="G_LCDCloseEnable",
            generation=generation,
            accepted=False,
            result="Rejected",
        )

        self.assertIsNone(
            writes.pending_configuration_value(state, "G_LCDCloseEnable")
        )


if __name__ == "__main__":
    unittest.main()
