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


if __name__ == "__main__":
    unittest.main()
