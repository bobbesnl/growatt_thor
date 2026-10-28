"""Tests for model-aware charging current limits."""

from __future__ import annotations

import unittest

from tests.support import PACKAGE_PATH, load_package_module

MODULE_PATH = PACKAGE_PATH / "charging/limits.py"
charging_limits = load_package_module("growatt_thor_charging_limits_test_target", MODULE_PATH)


class ChargingLimitsTest(unittest.TestCase):
    """Verify safe current limits for reported charger models."""

    def test_thor_models_use_their_electrical_limit(self):
        expectations = {
            "THOR_03AS-S": 16,
            "THOR_11AS": 16,
            "THOR_07AS-S": 32,
            "THOR_22AS": 32,
            "THOR_44AS": 63,
        }

        for model, expected in expectations.items():
            with self.subTest(model=model):
                self.assertEqual(
                    charging_limits.maximum_charging_current(model),
                    expected,
                )

    def test_web_interface_models_include_se_variants(self):
        expectations = {
            "EVA-11S": 16,
            "EVA-22S-SE": 32,
            "EVA-44S-SE": 63,
        }

        for model, expected in expectations.items():
            with self.subTest(model=model):
                self.assertEqual(
                    charging_limits.maximum_charging_current(model),
                    expected,
                )

    def test_firmware_string_can_supply_the_model(self):
        self.assertEqual(
            charging_limits.maximum_charging_current(
                "THOR",
                "THOR_22AS-V2.2.16-20240902",
            ),
            32,
        )

    def test_unknown_model_uses_conservative_default(self):
        self.assertEqual(
            charging_limits.maximum_charging_current("THOR", "V1.2.3"),
            32,
        )

    def test_conflicting_identity_values_use_lower_limit(self):
        self.assertEqual(
            charging_limits.maximum_charging_current(
                "THOR_11AS",
                "THOR_44AS-V1.0.0",
            ),
            16,
        )


if __name__ == "__main__":
    unittest.main()
