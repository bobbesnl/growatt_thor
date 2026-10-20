"""Tests for MeterValues-based effective charging time."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest


COMPONENT_PATH = Path(__file__).parents[1] / "custom_components" / "growatt_thor"
PACKAGE_NAME = "growatt_thor_charging_duration_test_target"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(COMPONENT_PATH)]
sys.modules[PACKAGE_NAME] = package


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.{name}", COMPONENT_PATH / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


meter_samples = _load("meter_samples")
duration = _load("charging_duration")


def _entry(timestamp: str, *, power_w=None, energy_wh=None):
    samples = []
    if power_w is not None:
        samples.append(
            {"value": str(power_w), "measurand": "Power.Active.Import", "unit": "W"}
        )
    if energy_wh is not None:
        samples.append(
            {
                "value": str(energy_wh),
                "measurand": "Energy.Active.Import.Register",
                "unit": "Wh",
            }
        )
    return meter_samples.parse_meter_values(
        {"timestamp": timestamp, "sampledValue": samples}
    )[0]


class EffectiveChargingTrackerTest(unittest.TestCase):
    def test_counts_only_powered_sample_intervals(self):
        tracker = duration.EffectiveChargingTracker()
        tracker.start(7)
        for entry in (
            _entry("2026-08-29T10:00:00Z", power_w=7000),
            _entry("2026-08-29T10:00:05Z", power_w=7000),
            _entry("2026-08-29T10:00:10Z", power_w=0),
            _entry("2026-08-29T10:00:15Z", power_w=0),
        ):
            tracker.observe(entry)

        self.assertEqual(tracker.elapsed_seconds, 10)
        self.assertEqual(tracker.effective_minutes, 0.2)

    def test_uses_increasing_energy_when_power_is_missing(self):
        tracker = duration.EffectiveChargingTracker(transaction_id="7")
        tracker.observe(_entry("2026-08-29T10:00:00Z", energy_wh=0))
        tracker.observe(_entry("2026-08-29T10:00:05Z", energy_wh=10))

        self.assertEqual(tracker.elapsed_seconds, 5)

    def test_does_not_count_network_gap(self):
        tracker = duration.EffectiveChargingTracker(transaction_id="7")
        tracker.observe(_entry("2026-08-29T10:00:00Z", power_w=7000))
        tracker.observe(
            _entry("2026-08-29T10:10:00Z", power_w=7000),
            max_gap_seconds=30,
        )

        self.assertEqual(tracker.elapsed_seconds, 0)
        self.assertIsNone(tracker.effective_minutes)

    def test_storage_round_trip_and_new_transaction_reset(self):
        tracker = duration.EffectiveChargingTracker(transaction_id="7")
        tracker.observe(_entry("2026-08-29T10:00:00Z", power_w=7000))
        tracker.observe(_entry("2026-08-29T10:00:05Z", power_w=7000))

        restored = duration.EffectiveChargingTracker.from_dict(tracker.as_dict())
        self.assertEqual(restored, tracker)
        restored.start(8)
        self.assertEqual(restored.transaction_id, "8")
        self.assertEqual(restored.elapsed_seconds, 0)
        self.assertIsNone(restored.effective_minutes)


if __name__ == "__main__":
    unittest.main()
