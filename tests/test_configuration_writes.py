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

    def test_accepted_write_waits_for_matching_readback(self):
        state = writes.begin_configuration_write(
            {},
            key="G_SolarMode",
            raw_value="1&1",
            requested_at="2026-08-24T10:00:00Z",
        )
        state = writes.acknowledge_configuration_write(
            state,
            key="G_SolarMode",
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
        state = writes.acknowledge_configuration_write(
            state,
            key="G_SolarMode",
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
        state = writes.acknowledge_configuration_write(
            state,
            key="G_SolarMode",
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
        state = writes.mark_configuration_write(
            state,
            key="G_MaxCurrent",
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
        state = writes.mark_configuration_write(
            state,
            key="G_MaxCurrent",
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
        state = writes.mark_configuration_write(
            state,
            key="G_AutoChargeTime",
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
        self.assertEqual(
            writes.pending_configuration_value(state, "G_LCDCloseEnable"),
            "Disable",
        )

        state = writes.acknowledge_configuration_write(
            state,
            key="G_LCDCloseEnable",
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
        state = writes.acknowledge_configuration_write(
            state,
            key="G_LCDCloseEnable",
            accepted=False,
            result="Rejected",
        )

        self.assertIsNone(
            writes.pending_configuration_value(state, "G_LCDCloseEnable")
        )


if __name__ == "__main__":
    unittest.main()
