"""Tests for restart-safe active-session persistence."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest


COMPONENT = Path(__file__).parents[1] / "custom_components" / "growatt_thor"
PACKAGE_NAME = "thor_active_session_state_test"
PACKAGE = types.ModuleType(PACKAGE_NAME)
PACKAGE.__path__ = [str(COMPONENT)]
sys.modules[PACKAGE_NAME] = PACKAGE


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.{name}", COMPONENT / (name.replace(".", "/") + ".py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_load('sessions.events')
_load('sessions.series')
active_session_state = _load('sessions.active_state')


class ActiveSessionStateTest(unittest.TestCase):
    def test_round_trip_preserves_active_row_curve_and_events(self):
        original = active_session_state.ActiveSessionState(
            transaction_id="27",
            id_tag="RFID-PRIVATE",
            start_received_at="2026-09-21T08:00:00Z",
            start_timestamp="2026-09-21T08:00:00Z",
            connector_id="1",
            meter_start=1200,
            energy_wh=4300,
            power_curve=[["2026-09-21T08:01:00Z", 7100]],
            events=[
                {
                    "type": "transaction_started",
                    "at": "2026-09-21T08:00:00Z",
                    "source": "ocpp",
                    "certainty": "observed",
                }
            ],
            energy_flowing=True,
        )

        restored = active_session_state.ActiveSessionState.from_dict(
            original.as_dict()
        )

        self.assertEqual(restored, original)

    def test_invalid_values_are_filtered_and_curve_is_bounded(self):
        restored = active_session_state.ActiveSessionState.from_dict(
            {
                "transaction_id": 27,
                "energy_wh": -1,
                "energy_flowing": "yes",
                "power_curve": [
                    [f"2026-09-21T08:{index // 60:02d}:{index % 60:02d}Z", index]
                    for index in range(200)
                ]
                + [["bad", 12], ["2026-09-21T09:00:00Z", -1]],
                "events": [{"type": "invalid"}],
            }
        )

        self.assertEqual(restored.transaction_id, "27")
        self.assertIsNone(restored.energy_wh)
        self.assertIsNone(restored.energy_flowing)
        self.assertEqual(
            len(restored.power_curve),
            active_session_state.SESSION_CURVE_POINT_LIMIT,
        )
        self.assertEqual(restored.events, [])


if __name__ == "__main__":
    unittest.main()
