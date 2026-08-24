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


if __name__ == "__main__":
    unittest.main()
