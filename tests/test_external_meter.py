"""Tests for Growatt external-meter payload parsing."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
    / "external_meter.py"
)
SPEC = importlib.util.spec_from_file_location(
    "growatt_thor_external_meter_test_target",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
external_meter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = external_meter
SPEC.loader.exec_module(external_meter)


class ExternalMeterParserTest(unittest.TestCase):
    """Verify observed get_external_meterval payloads."""

    def test_parses_observed_three_phase_payload(self):
        snapshot = external_meter.parse_external_meter_data(
            "used=1&wring=1&u-voltage=234&v-voltage=233&"
            "w-voltage=233&u-current=5&v-current=4&w-current=4&power=-3446"
        )

        self.assertEqual(snapshot.used, 1)
        self.assertEqual(snapshot.wring, 1)
        self.assertEqual(snapshot.power, -3446.0)
        self.assertEqual(
            snapshot.voltages,
            {"L1": 234.0, "L2": 233.0, "L3": 233.0},
        )
        self.assertEqual(
            snapshot.currents,
            {"L1": 5.0, "L2": 4.0, "L3": 4.0},
        )

    def test_preserves_real_zero_values(self):
        snapshot = external_meter.parse_external_meter_data(
            "used=1&wring=1&u-voltage=230&u-current=0&power=0"
        )

        self.assertEqual(snapshot.power, 0.0)
        self.assertEqual(snapshot.voltages, {"L1": 230.0})
        self.assertEqual(snapshot.currents, {"L1": 0.0})

    def test_missing_or_invalid_values_remain_absent(self):
        snapshot = external_meter.parse_external_meter_data(
            "used=&wring=invalid&u-voltage=not-a-number&v-voltage=232.5"
        )

        self.assertIsNone(snapshot.used)
        self.assertIsNone(snapshot.wring)
        self.assertIsNone(snapshot.power)
        self.assertEqual(snapshot.voltages, {"L2": 232.5})
        self.assertEqual(snapshot.currents, {})

    def test_rejects_non_string_payload(self):
        with self.assertRaises(TypeError):
            external_meter.parse_external_meter_data(None)


class ExternalMeterHealthTest(unittest.TestCase):
    """Verify explicit faults and sustained communication failures."""

    def test_detects_observed_power_meter_failure(self):
        self.assertTrue(
            external_meter.status_reports_external_meter_fault(
                "PowerMeterFailure",
                "485 Fault",
            )
        )
        self.assertTrue(
            external_meter.status_reports_external_meter_fault(None, "485 Fault")
        )
        self.assertFalse(
            external_meter.status_reports_external_meter_fault("NoError", None)
        )
        self.assertTrue(
            external_meter.status_clears_external_meter_fault("NoError")
        )

    def test_explicit_fault_takes_priority_over_fresh_zero_snapshot(self):
        self.assertEqual(
            external_meter.external_meter_health(
                explicit_fault=True,
                consecutive_timeouts=0,
                has_snapshot=True,
            ),
            "faulted",
        )

    def test_three_consecutive_timeouts_are_required_for_stale(self):
        for timeouts in (0, 1, 2):
            with self.subTest(timeouts=timeouts):
                self.assertEqual(
                    external_meter.external_meter_health(
                        explicit_fault=False,
                        consecutive_timeouts=timeouts,
                        has_snapshot=True,
                    ),
                    "healthy",
                )
        self.assertEqual(
            external_meter.external_meter_health(
                explicit_fault=False,
                consecutive_timeouts=3,
                has_snapshot=True,
            ),
            "stale",
        )

    def test_missing_initial_snapshot_is_not_reported(self):
        self.assertEqual(
            external_meter.external_meter_health(
                explicit_fault=False,
                consecutive_timeouts=0,
                has_snapshot=False,
            ),
            "not_reported",
        )


if __name__ == "__main__":
    unittest.main()
