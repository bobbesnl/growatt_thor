"""Tests for persistent last-session entity state."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
    / "session_state.py"
)
SPEC = importlib.util.spec_from_file_location(
    "growatt_thor_session_state_test_target",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
session_state = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = session_state
SPEC.loader.exec_module(session_state)


class LastSessionStateTest(unittest.TestCase):
    """Verify storage round trips and defensive migration behavior."""

    def test_round_trip_preserves_entity_values_and_record_key(self):
        original = session_state.LastSessionState(
            energy_kwh=0.412,
            cost=0.09,
            start_time="2026-08-24 10:00:00",
            end_time="2026-08-24 10:30:00",
            plug_time="2026-08-24 09:55:00",
            unplug_time="2026-08-24 10:31:00",
            duration_minutes=30.0,
            transaction_id="7",
            charge_mode="3",
            work_mode="0",
            record_key=("7", "2026-08-24 10:30:00"),
        )

        stored = original.as_dict()
        restored = session_state.LastSessionState.from_dict(stored)

        self.assertEqual(restored, original)
        self.assertEqual(
            stored["record_key"],
            ["7", "2026-08-24 10:30:00"],
        )

    def test_invalid_optional_values_do_not_break_storage_loading(self):
        restored = session_state.LastSessionState.from_dict(
            {
                "energy_kwh": "invalid",
                "cost": "0.23",
                "duration_minutes": "5.5",
                "transaction_id": 9,
                "record_key": ["9"],
            }
        )

        self.assertIsNone(restored.energy_kwh)
        self.assertEqual(restored.cost, 0.23)
        self.assertEqual(restored.duration_minutes, 5.5)
        self.assertEqual(restored.transaction_id, "9")
        self.assertIsNone(restored.record_key)

    def test_missing_legacy_state_restores_empty_summary(self):
        self.assertEqual(
            session_state.LastSessionState.from_dict(None),
            session_state.LastSessionState(),
        )


if __name__ == "__main__":
    unittest.main()
