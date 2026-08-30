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

    def test_unhealthy_external_meter_hides_pv_modes_but_keeps_current_mode(self):
        self.assertEqual(
            controls.available_working_mode_options(
                "fast",
                external_meter_ready=False,
            ),
            ["fast", "off_peak"],
        )
        self.assertEqual(
            controls.available_working_mode_options(
                "pv_linkage_plus",
                external_meter_ready=False,
            ),
            ["fast", "pv_linkage_plus", "off_peak"],
        )
        self.assertEqual(
            controls.available_working_mode_options(
                "fast",
                external_meter_ready=True,
            ),
            list(controls.WORKING_MODE_OPTIONS),
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
        self.assertFalse(
            controls.control_is_applicable(
                control,
                _values(G_WorkingMode="PVlink", G_SolarMode="1&2"),
            )
        )
        self.assertEqual(
            controls.control_write_block_reason(
                control,
                _values(G_WorkingMode="PVlink", G_SolarMode="1&2"),
                connected=True,
                transaction_active=False,
            ),
            "control_not_applicable",
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

    def test_power_meter_settings_require_power_meter_sampling(self):
        for control in (
            controls.ChargingControl.POWER_METER_TYPE,
            controls.ChargingControl.POWER_METER_ADDRESS,
        ):
            with self.subTest(control=control.value):
                self.assertFalse(
                    controls.control_is_applicable(
                        control,
                        _values(G_ExternalSamplingCurWring="0"),
                    )
                )
                self.assertTrue(
                    controls.control_is_applicable(
                        control,
                        _values(G_ExternalSamplingCurWring="1"),
                    )
                )

    def test_configuration_controls_are_blocked_while_charging(self):
        self.assertEqual(
            controls.control_write_block_reason(
                controls.ChargingControl.WORKING_MODE,
                _values(G_WorkingMode="Fast"),
                connected=True,
                transaction_active=True,
            ),
            "active_transaction",
        )

    def test_control_write_requires_connection_and_applicable_mode(self):
        control = controls.ChargingControl.SOLAR_GRID_IMPORT_LIMIT
        values = _values(G_WorkingMode="PVlink", G_SolarMode="1&1")
        self.assertEqual(
            controls.control_write_block_reason(
                control,
                values,
                connected=False,
                transaction_active=False,
            ),
            "charger_disconnected",
        )
        self.assertIsNone(
            controls.control_write_block_reason(
                control,
                values,
                connected=True,
                transaction_active=False,
            )
        )

    def test_direct_control_respects_reported_readonly_flag(self):
        values = {
            "G_FullContinueChargeEnable": (
                configuration.configuration_value_from_item(
                    {
                        "key": "G_FullContinueChargeEnable",
                        "value": "Disable",
                        "readonly": True,
                    }
                )
            )
        }
        self.assertEqual(
            controls.control_write_block_reason(
                controls.ChargingControl.WARM_UP,
                values,
                connected=True,
                transaction_active=False,
            ),
            "configuration_read_only",
        )

    def test_transaction_guard_survives_partial_reconnect_state(self):
        for state in (
            {
                "active_transaction": {"start": {}},
                "transaction_id": None,
                "status": "Available",
            },
            {
                "active_transaction": None,
                "transaction_id": 42,
                "status": "Available",
            },
            {
                "active_transaction": None,
                "transaction_id": None,
                "status": "SuspendedEV",
            },
        ):
            with self.subTest(state=state):
                self.assertTrue(controls.transaction_state_is_active(**state))

        self.assertFalse(
            controls.transaction_state_is_active(
                active_transaction=None,
                transaction_id=None,
                status="Available",
            )
        )

    def test_compound_and_unverified_settings_remain_read_only(self):
        expected = {
            controls.ChargingControl.SOLAR_BOOST:
                controls.ControlCapability.COMPOUND,
            controls.ChargingControl.OFF_PEAK_SCHEDULE:
                controls.ControlCapability.COMPOUND,
            controls.ChargingControl.SOLAR_THRESHOLD_CURRENT:
                controls.ControlCapability.READ_ONLY,
            controls.ChargingControl.GRID_OFF_PEAK_CHARGING:
                controls.ControlCapability.READ_ONLY,
            controls.ChargingControl.OFF_PEAK_CURRENT:
                controls.ControlCapability.READ_ONLY,
            controls.ChargingControl.OFF_PEAK_ENABLE:
                controls.ControlCapability.READ_ONLY,
            controls.ChargingControl.DELAYED_CHARGING:
                controls.ControlCapability.READ_ONLY,
        }
        for control, capability in expected.items():
            with self.subTest(control=control.value):
                self.assertEqual(
                    controls.CONTROL_DEFINITIONS[control].capability,
                    capability,
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
                controls.ChargingControl.WARM_UP,
                False,
            ),
            "Disable",
        )

    def test_external_sampling_method_uses_ocpp_values(self):
        for logical, raw in (
            ("ct_2000_1", "0"),
            ("power_meter", "1"),
            ("ct_3000_1", "2"),
        ):
            with self.subTest(logical=logical):
                self.assertEqual(
                    controls.encode_control_value(
                        controls.ChargingControl.EXTERNAL_SAMPLING_METHOD,
                        logical,
                    ),
                    raw,
                )

    def test_external_sampling_method_rejects_web_ui_null_value(self):
        with self.assertRaises(ValueError):
            controls.encode_control_value(
                controls.ChargingControl.EXTERNAL_SAMPLING_METHOD,
                "null",
            )

    def test_power_meter_type_uses_web_ui_and_ocpp_codes(self):
        for logical, raw in (
            ("none", "0"),
            ("acrel_dds1352", "1"),
            ("acrel_dtsd1352_three", "2"),
            ("eastron_sdm230", "3"),
            ("eastron_sdm630_three", "4"),
            ("eastron_sdm120_mid", "5"),
            ("eastron_sdm72d_mid_three", "6"),
            ("din_rail_dtsu666_mid_three", "7"),
            ("chint_dtsu666_mid_three", "10"),
            ("chint_ddsu666", "11"),
        ):
            with self.subTest(logical=logical):
                self.assertEqual(
                    controls.encode_control_value(
                        controls.ChargingControl.POWER_METER_TYPE,
                        logical,
                    ),
                    raw,
                )

    def test_power_meter_address_requires_valid_modbus_address(self):
        self.assertEqual(
            controls.encode_control_value(
                controls.ChargingControl.POWER_METER_ADDRESS,
                2,
            ),
            "2",
        )
        for invalid in (0, 1.5, 248):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                controls.encode_control_value(
                    controls.ChargingControl.POWER_METER_ADDRESS,
                    invalid,
                )

    def test_compound_control_cannot_be_encoded_in_isolation(self):
        with self.assertRaises(ValueError):
            controls.encode_control_value(
                controls.ChargingControl.SOLAR_BOOST,
                "smart",
            )

    def test_working_mode_uses_captured_indirect_keys(self):
        for option, encoded in (
            ("fast", ("G_SolarMode", "1&0")),
            ("pv_linkage", ("G_SolarMode", "1&1")),
            ("pv_linkage_plus", ("G_SolarMode", "1&2")),
            ("off_peak", ("G_OffPeakEnable", "1&Enable")),
        ):
            with self.subTest(option=option):
                self.assertEqual(controls.encode_working_mode(option), encoded)

    def test_selected_working_mode_includes_pv_submode(self):
        self.assertEqual(
            controls.selected_working_mode(
                _values(G_WorkingMode="PVlink", G_SolarMode="1&2")
            ),
            "pv_linkage_plus",
        )
        self.assertEqual(
            controls.selected_working_mode(
                _values(G_WorkingMode="Off Peak", G_SolarMode="1&0")
            ),
            "off_peak",
        )


if __name__ == "__main__":
    unittest.main()
