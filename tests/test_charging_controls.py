"""Tests for mode-aware Growatt charging controls."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest


PACKAGE_PATH = (
    Path(__file__).parents[1] / "custom_components" / "growatt_thor"
)
PACKAGE_NAME = "growatt_thor_control_test_target"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(PACKAGE_PATH)]
sys.modules[PACKAGE_NAME] = package


def _load_module(name: str):
    path = PACKAGE_PATH / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{PACKAGE_NAME}.{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


configuration = _load_module("configuration")
controls = _load_module("charging_controls")


def _values(**raw_values):
    return {
        key: configuration.configuration_value_from_item(
            {"key": key, "value": value, "readonly": False}
        )
        for key, value in raw_values.items()
    }


class ChargingControlDependencyTest(unittest.TestCase):
    """Verify mode and authorization dependencies."""

    def test_load_balancing_is_not_applicable_in_pv_linkage(self):
        self.assertFalse(
            controls.control_is_applicable(
                controls.ChargingControl.LOAD_BALANCING,
                _values(G_WorkingMode="PVlink"),
            )
        )
        self.assertTrue(
            controls.control_is_applicable(
                controls.ChargingControl.LOAD_BALANCING,
                _values(G_WorkingMode="Off Peak"),
            )
        )

    def test_solar_limit_requires_pv_mode_and_enabled_solar_mode(self):
        control = controls.ChargingControl.SOLAR_GRID_IMPORT_LIMIT
        self.assertFalse(
            controls.control_is_applicable(
                control,
                _values(G_WorkingMode="Fast", G_SolarMode="1&1"),
            )
        )
        self.assertFalse(
            controls.control_is_applicable(
                control,
                _values(G_WorkingMode="PVlink", G_SolarMode="1&0"),
            )
        )
        self.assertTrue(
            controls.control_is_applicable(
                control,
                _values(G_WorkingMode="PVlink", G_SolarMode="1&1"),
            )
        )

    def test_grid_off_peak_requires_plug_and_charge(self):
        control = controls.ChargingControl.GRID_OFF_PEAK_CHARGING
        self.assertFalse(
            controls.control_is_applicable(
                control,
                _values(G_ChargerMode="2"),
            )
        )
        self.assertTrue(
            controls.control_is_applicable(
                control,
                _values(G_ChargerMode="3"),
            )
        )

    def test_global_warm_up_control_has_no_mode_dependency(self):
        self.assertTrue(
            controls.control_is_applicable(
                controls.ChargingControl.WARM_UP,
                {},
            )
        )


class ChargingControlEncodingTest(unittest.TestCase):
    """Verify captured Growatt payload encodings."""

    def test_solar_modes_include_connector_prefix(self):
        for logical, raw in (
            ("disabled", "1&0"),
            ("pv_linkage", "1&1"),
            ("pv_linkage_plus", "1&2"),
        ):
            with self.subTest(logical=logical):
                self.assertEqual(
                    controls.encode_control_value(
                        controls.ChargingControl.SOLAR_MODE,
                        logical,
                    ),
                    raw,
                )

    def test_decimal_values_always_use_dot_notation(self):
        self.assertEqual(
            controls.encode_control_value(
                controls.ChargingControl.SOLAR_GRID_IMPORT_LIMIT,
                4.2,
            ),
            "4.2",
        )

    def test_boolean_payloads_match_captured_values(self):
        self.assertEqual(
            controls.encode_control_value(
                controls.ChargingControl.OFF_PEAK_ENABLE,
                True,
            ),
            "1&Enable",
        )
        self.assertEqual(
            controls.encode_control_value(
                controls.ChargingControl.WARM_UP,
                False,
            ),
            "Disable",
        )

    def test_compound_control_cannot_be_encoded_in_isolation(self):
        with self.assertRaises(ValueError):
            controls.encode_control_value(
                controls.ChargingControl.SOLAR_BOOST,
                "smart",
            )


if __name__ == "__main__":
    unittest.main()
