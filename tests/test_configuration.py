"""Tests for the standalone configuration registry."""
from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
    / "configuration.py"
)
TRANSLATIONS_PATH = MODULE_PATH.parent / "translations"
SENSOR_PATH = MODULE_PATH.parent / "sensor.py"
CONTROL_PATHS = tuple(
    MODULE_PATH.parent / f"{platform}.py"
    for platform in ("button", "number", "select", "switch", "time")
)
SPEC = importlib.util.spec_from_file_location(
    "growatt_thor_configuration_test_target",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
configuration = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = configuration
SPEC.loader.exec_module(configuration)


class ConfigurationRegistryTest(unittest.TestCase):
    """Verify request groups and metadata."""

    def test_request_groups_preserve_existing_key_order(self):
        self.assertEqual(
            configuration.OPERATIONAL_CONFIGURATION_KEYS,
            (
                "G_MaxCurrent",
                "G_ExternalLimitPower",
                "G_ExternalLimitPowerEnable",
                "G_ChargerMode",
                "G_ServerURL",
                "G_AutoChargeTime",
                "G_LCDCloseEnable",
                "HeartbeatInterval",
                "MeterValueSampleInterval",
                "MeterValuesSampledData",
                "UnlockConnectorOnEVSideDisconnect",
                "ElectricityMeterOnline",
                "G_WebSocketPingInterval",
                "G_TimeSharingPrice",
                "G_PeriodTime",
            ),
        )
        self.assertEqual(
            configuration.INFORMATIONAL_CONFIGURATION_KEYS,
            (
                "G_ChargerID",
                "G_ChargerRate",
                "G_ChargerLanguage",
                "G_ChargerNetIP",
                "G_ChargerNetDNS",
                "G_ChargerNetMask",
                "G_ChargerNetMac",
                "G_ChargerNetGateway",
                "G_NetworkMode",
                "G_WifiSSID",
                "G_MaxTemperature",
                "G_RCDProtection",
                "G_PowerMeterAddr",
                "G_PowerMeterType",
                "G_ExternalSamplingCurWring",
                "G_TimeZone",
                "G_DaylightSavingTime",
                "G_SolarMode",
                "G_SolarLimitPower",
                "G_SolarBoost",
                "G_SolarThresholdCurr",
                "G_PeakValleyEnable",
                "G_OffPeakTime",
                "G_OffPeakEnable",
                "G_OffPeakCurr",
                "G_MeterValueInterval",
                "G_WorkingMode",
                "G_LowPowerReserveEnable",
                "G_FullContinueChargeEnable",
                "G_RandDelayChargeTime",
            ),
        )

    def test_informational_request_respects_firmware_limit(self):
        self.assertLessEqual(
            len(configuration.INFORMATIONAL_CONFIGURATION_KEYS),
            30,
        )

    def test_secret_keys_are_not_requested(self):
        requested = set(configuration.OPERATIONAL_CONFIGURATION_KEYS)
        requested.update(configuration.INFORMATIONAL_CONFIGURATION_KEYS)

        for key in requested:
            self.assertNotEqual(
                configuration.CONFIGURATION_REGISTRY[key].sensitivity,
                configuration.ConfigurationSensitivity.SECRET,
            )


class ConfigurationValueTest(unittest.TestCase):
    """Verify lossless value parsing and serialization."""

    def test_known_values_keep_raw_and_parsed_forms(self):
        value = configuration.configuration_value_from_item(
            {"key": "G_MaxCurrent", "value": "32.00", "readonly": False}
        )

        self.assertIsNotNone(value)
        self.assertEqual(value.raw_value, "32.00")
        self.assertEqual(value.parsed_value, 32.0)
        self.assertFalse(value.readonly)
        self.assertTrue(value.known)

    def test_enum_value_has_label(self):
        value = configuration.configuration_value_from_item(
            {"key": "G_ChargerMode", "value": "3", "readonly": False}
        )

        self.assertEqual(value.parsed_value, 3)
        self.assertEqual(value.enum_label, "Plug & Charge")

    def test_invalid_typed_value_falls_back_to_raw_value(self):
        value = configuration.configuration_value_from_item(
            {"key": "G_MaxCurrent", "value": "not-a-number", "readonly": True}
        )

        self.assertEqual(value.raw_value, "not-a-number")
        self.assertEqual(value.parsed_value, "not-a-number")

    def test_unknown_value_is_preserved_and_redacted_by_default(self):
        value = configuration.configuration_value_from_item(
            {"key": "FutureKey", "value": "opaque", "readonly": True}
        )

        self.assertFalse(value.known)
        self.assertEqual(value.raw_value, "opaque")
        self.assertEqual(value.as_dict()["raw_value"], "opaque")
        self.assertEqual(value.as_dict(redact=True)["raw_value"], "<redacted>")
        self.assertEqual(
            value.as_dict(redact=True)["sensitivity"],
            configuration.ConfigurationSensitivity.UNKNOWN.value,
        )

    def test_merge_updates_values_without_dropping_previous_keys(self):
        current, _ = configuration.merge_configuration_values(
            {},
            [{"key": "G_MaxCurrent", "value": "16", "readonly": False}],
        )
        merged, changed = configuration.merge_configuration_values(
            current,
            [{"key": "G_ChargerMode", "value": "2", "readonly": False}],
        )

        self.assertTrue(changed)
        self.assertEqual(set(merged), {"G_MaxCurrent", "G_ChargerMode"})

    def test_sensitive_values_are_redacted(self):
        self.assertEqual(
            configuration.redact_configuration_value(
                "G_ChargerNetIP",
                "192.0.2.1",
            ),
            "<redacted>",
        )
        self.assertEqual(
            configuration.redact_configuration_value("FutureKey", "opaque"),
            "<redacted>",
        )

    def test_unknown_keys_are_stable_and_unique(self):
        self.assertEqual(
            configuration.normalize_unknown_configuration_keys(
                ["G_RFEnable", "LightIntensity", "G_RFEnable", None]
            ),
            ("G_RFEnable", "LightIntensity"),
        )


class ConfigurationEntityStateTest(unittest.TestCase):
    """Verify stable states for read-only Home Assistant entities."""

    @staticmethod
    def _value(key: str, raw_value: str):
        return configuration.configuration_value_from_item(
            {"key": key, "value": raw_value, "readonly": True}
        )

    def test_working_mode_aliases(self):
        for raw_value, expected in (
            ("Fast", "fast"),
            ("PVlink", "pv_linkage"),
            ("PV Linkage", "pv_linkage"),
            ("PVlink ManualBoost", "pv_linkage"),
            ("PVlink SmartBoost", "pv_linkage"),
            ("Off-Peak", "off_peak"),
            ("Power Distribution", "power_distribution"),
        ):
            with self.subTest(raw_value=raw_value):
                self.assertEqual(
                    configuration.configuration_entity_state(
                        "G_WorkingMode",
                        self._value("G_WorkingMode", raw_value),
                    ),
                    expected,
                )

    def test_charger_mode_values(self):
        for raw_value, expected in (
            ("1", "home_assistant_rfid"),
            ("2", "rfid_only"),
            ("3", "plug_and_charge"),
        ):
            with self.subTest(raw_value=raw_value):
                self.assertEqual(
                    configuration.configuration_entity_state(
                        "G_ChargerMode",
                        self._value("G_ChargerMode", raw_value),
                    ),
                    expected,
                )

    def test_external_sampling_wiring_values(self):
        for raw_value, expected in (
            ("0", "ct_2000_1"),
            ("1", "power_meter"),
            ("2", "ct_3000_1"),
        ):
            with self.subTest(raw_value=raw_value):
                self.assertEqual(
                    configuration.configuration_entity_state(
                        "G_ExternalSamplingCurWring",
                        self._value("G_ExternalSamplingCurWring", raw_value),
                    ),
                    expected,
                )

        self.assertIsNone(
            configuration.configuration_entity_state(
                "G_ExternalSamplingCurWring",
                self._value("G_ExternalSamplingCurWring", "3"),
            )
        )

    def test_solar_mode_values(self):
        for raw_value, expected in (
            ("0", "disabled"),
            ("1", "pv_linkage"),
            ("2", "pv_linkage_plus"),
            ("1&0", "disabled"),
            ("1&1", "pv_linkage"),
            ("1&2", "pv_linkage_plus"),
        ):
            with self.subTest(raw_value=raw_value):
                self.assertEqual(
                    configuration.configuration_entity_state(
                        "G_SolarMode",
                        self._value("G_SolarMode", raw_value),
                    ),
                    expected,
                )

    def test_peak_valley_enable_values(self):
        for raw_value, expected in (
            ("0", "disabled"),
            ("Disable", "disabled"),
            ("1", "enabled"),
            ("Enable", "enabled"),
        ):
            with self.subTest(raw_value=raw_value):
                self.assertEqual(
                    configuration.configuration_entity_state(
                        "G_PeakValleyEnable",
                        self._value("G_PeakValleyEnable", raw_value),
                    ),
                    expected,
                )

    def test_solar_boost_values(self):
        for raw_value, expected in (
            ("1&Disable", "disabled"),
            ("1&ManualBoost", "manual"),
            ("1&SmartBoost", "smart"),
        ):
            with self.subTest(raw_value=raw_value):
                self.assertEqual(
                    configuration.configuration_entity_state(
                        "G_SolarBoost",
                        self._value("G_SolarBoost", raw_value),
                    ),
                    expected,
                )

    def test_off_peak_enable_values(self):
        for raw_value, expected in (
            ("1&Disable", "disabled"),
            ("1&Enable", "enabled"),
        ):
            with self.subTest(raw_value=raw_value):
                self.assertEqual(
                    configuration.configuration_entity_state(
                        "G_OffPeakEnable",
                        self._value("G_OffPeakEnable", raw_value),
                    ),
                    expected,
                )

    def test_warm_up_values(self):
        for raw_value, expected in (
            ("Disable", "disabled"),
            ("Enable", "enabled"),
        ):
            with self.subTest(raw_value=raw_value):
                self.assertEqual(
                    configuration.configuration_entity_state(
                        "G_FullContinueChargeEnable",
                        self._value("G_FullContinueChargeEnable", raw_value),
                    ),
                    expected,
                )

    def test_off_peak_schedule_extracts_time_windows(self):
        for raw_value, expected in (
            ("00:00-05:00=0&1", "00:00-05:00"),
            (
                "12:00-13:00=0&00:00-05:00=0&1",
                "12:00-13:00, 00:00-05:00",
            ),
        ):
            with self.subTest(raw_value=raw_value):
                value = self._value("G_OffPeakTime", raw_value)
                self.assertEqual(value.raw_value, raw_value)
                self.assertEqual(
                    configuration.configuration_entity_state(
                        "G_OffPeakTime",
                        value,
                    ),
                    expected,
                )

    def test_mode_specific_numeric_settings_include_units(self):
        for key, raw_value, parsed_value, unit in (
            ("G_SolarLimitPower", "3.96", 3.96, "kW"),
            ("G_SolarThresholdCurr", "6", 6.0, "A"),
            ("G_OffPeakCurr", "16", 16.0, "A"),
            ("G_RandDelayChargeTime", "600", 600, "s"),
        ):
            with self.subTest(key=key):
                value = self._value(key, raw_value)
                self.assertEqual(value.parsed_value, parsed_value)
                self.assertEqual(value.definition.unit, unit)

    def test_plain_meter_values_keep_their_parsed_type(self):
        self.assertEqual(
            configuration.configuration_entity_state(
                "G_PowerMeterType",
                self._value("G_PowerMeterType", "Eastron SDM630"),
            ),
            "Eastron SDM630",
        )
        self.assertEqual(
            configuration.configuration_entity_state(
                "G_PowerMeterAddr",
                self._value("G_PowerMeterAddr", "2"),
            ),
            2,
        )

    def test_unmapped_or_empty_enum_value_is_unavailable(self):
        self.assertIsNone(
            configuration.configuration_entity_state(
                "G_WorkingMode",
                self._value("G_WorkingMode", "FutureMode"),
            )
        )
        self.assertIsNone(
            configuration.configuration_entity_state(
                "G_WorkingMode",
                self._value("G_WorkingMode", ""),
            )
        )


class EntityTranslationTest(unittest.TestCase):
    """Keep translated enum states aligned with the entity contract."""

    def test_configuration_entities_are_translated(self):
        expected_entities = {
            "server_url",
            "status",
            "charge_point_id",
            "charging_power",
            "energy_charged",
            "total_energy_charged",
            "electricity_price",
            "last_session_energy",
            "last_session_cost",
            "last_session_duration",
            "last_session_start",
            "last_session_end",
            "last_session_plug_time",
            "last_session_unplug_time",
            "last_session_transaction_id",
            "last_session_charge_mode",
            "last_session_work_mode",
            "current",
            "voltage",
            "phase_power",
            "temperature",
            "grid_power",
            "grid_voltage",
            "grid_current",
            "working_mode",
            "charger_mode",
            "solar_mode",
            "solar_grid_import_limit",
            "solar_boost",
            "solar_threshold_current",
            "grid_off_peak_charging",
            "off_peak_enable_setting",
            "off_peak_schedule",
            "off_peak_current",
            "power_meter_type",
            "power_meter_address",
            "reported_external_sampling_method",
            "warm_up_after_full_charge",
            "delayed_charging_time",
        }
        enum_entities = {
            "working_mode": "G_WorkingMode",
            "charger_mode": "G_ChargerMode",
            "solar_mode": "G_SolarMode",
            "grid_off_peak_charging": "G_PeakValleyEnable",
            "solar_boost": "G_SolarBoost",
            "off_peak_enable_setting": "G_OffPeakEnable",
            "reported_external_sampling_method": "G_ExternalSamplingCurWring",
            "warm_up_after_full_charge": "G_FullContinueChargeEnable",
        }
        session_enum_entities = {
            "last_session_charge_mode": (
                "home_assistant_rfid",
                "rfid_only",
                "plug_and_charge",
                "unknown_mode",
            ),
            "last_session_work_mode": (
                "fast",
                "pv_linkage",
                "off_peak",
                "unknown_mode",
            ),
        }
        informative_entities = {
            "working_mode",
            "charger_mode",
            "solar_mode",
            "solar_grid_import_limit",
            "solar_boost",
            "grid_off_peak_charging",
            "off_peak_enable_setting",
            "off_peak_schedule",
            "off_peak_current",
            "power_meter_type",
            "power_meter_address",
            "reported_external_sampling_method",
            "warm_up_after_full_charge",
            "delayed_charging_time",
        }

        for language in ("en", "de", "nl"):
            with self.subTest(language=language):
                translation = json.loads(
                    (TRANSLATIONS_PATH / f"{language}.json").read_text(
                        encoding="utf-8"
                    )
                )
                sensors = translation["entity"]["sensor"]
                self.assertTrue(expected_entities.issubset(sensors))
                self.assertEqual(
                    tuple(sensors["status"]["state"]),
                    (
                        "available",
                        "preparing",
                        "charging",
                        "suspended_evse",
                        "suspended_ev",
                        "finishing",
                        "reserved",
                        "unavailable",
                        "faulted",
                        "idle",
                    ),
                )

                for translation_key, configuration_key in enum_entities.items():
                    self.assertEqual(
                        tuple(sensors[translation_key]["state"]),
                        configuration.CONFIGURATION_ENTITY_OPTIONS[
                            configuration_key
                        ],
                    )

                for translation_key, options in session_enum_entities.items():
                    self.assertEqual(
                        tuple(sensors[translation_key]["state"]),
                        options,
                    )

                for translation_key in informative_entities:
                    information = sensors[translation_key]["state_attributes"][
                        "information"
                    ]
                    self.assertTrue(information["name"])
                    self.assertEqual(tuple(information["state"]), ("details",))
                    self.assertTrue(information["state"]["details"])

        self.assertIn(
            'attributes["information"] = "details"',
            SENSOR_PATH.read_text(encoding="utf-8"),
        )

    def test_existing_sensor_names_use_translation_keys(self):
        tree = ast.parse(SENSOR_PATH.read_text(encoding="utf-8"))
        hardcoded_names = []
        translation_keys = set()

        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                attribute = (
                    target.id
                    if isinstance(target, ast.Name)
                    else target.attr
                    if isinstance(target, ast.Attribute)
                    else None
                )
                if attribute == "_attr_name":
                    hardcoded_names.append(node.lineno)
                elif (
                    attribute == "_attr_translation_key"
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    translation_keys.add(node.value.value)

        self.assertEqual(hardcoded_names, [])
        self.assertTrue(
            {
                "status",
                "charging_power",
                "electricity_price",
                "last_session_energy",
                "current",
                "voltage",
                "phase_power",
                "grid_power",
                "grid_voltage",
                "grid_current",
            }.issubset(translation_keys)
        )

    def test_control_entities_are_translated(self):
        expected = {
            "button": {
                "start_charging",
                "stop_charging",
                "apply_pv_linkage",
            },
            "number": {
                "max_current",
                "load_balancing_limit",
                "electricity_price",
                "solar_grid_import_limit",
                "pv_smart_boost_target_energy",
            },
            "select": {
                "working_mode",
                "external_sampling_method",
                "pv_boost_mode",
            },
            "switch": {
                "load_balancing",
                "lcd_display",
                "warm_up",
            },
            "time": {
                "auto_charge_start_time",
                "auto_charge_stop_time",
                "pv_manual_boost_start",
                "pv_manual_boost_end",
                "pv_smart_boost_finish",
            },
        }

        for language in ("en", "de", "nl"):
            with self.subTest(language=language):
                translation = json.loads(
                    (TRANSLATIONS_PATH / f"{language}.json").read_text(
                        encoding="utf-8"
                    )
                )
                entities = translation["entity"]
                for platform, keys in expected.items():
                    self.assertTrue(keys.issubset(entities[platform]))
                self.assertEqual(
                    tuple(entities["select"]["working_mode"]["state"]),
                    ("fast", "pv_linkage", "pv_linkage_plus", "off_peak"),
                )
                for platform, key in (
                    ("number", "solar_grid_import_limit"),
                    ("select", "working_mode"),
                    ("switch", "warm_up"),
                ):
                    information = entities[platform][key]["state_attributes"][
                        "information"
                    ]
                    self.assertTrue(information["name"])
                    self.assertTrue(information["state"]["details"])

    def test_control_entities_do_not_use_hardcoded_names(self):
        hardcoded_names = []
        for path in CONTROL_PATHS:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and target.attr == "_attr_name"
                    ):
                        hardcoded_names.append((path.name, node.lineno))

        self.assertEqual(hardcoded_names, [])

    def test_direct_control_shadow_sensors_are_disabled_by_default(self):
        tree = ast.parse(SENSOR_PATH.read_text(encoding="utf-8"))
        defaults = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name):
                continue
            if node.func.id != "SensorEntityDescription":
                continue
            keywords = {keyword.arg: keyword.value for keyword in node.keywords}
            key_node = keywords.get("key")
            default_node = keywords.get("entity_registry_enabled_default")
            if (
                isinstance(key_node, ast.Constant)
                and isinstance(key_node.value, str)
                and isinstance(default_node, ast.Constant)
            ):
                defaults[key_node.value] = default_node.value

        shadow_keys = {
            "working_mode",
            "solar_mode",
            "solar_grid_import_limit",
            "off_peak_enable_setting",
            "warm_up_after_full_charge",
            "external_sampling_wiring",
            "solar_boost",
        }
        self.assertEqual(
            {key: defaults.get(key) for key in shadow_keys},
            {key: False for key in shadow_keys},
        )

        sensor_source = SENSOR_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "_attr_entity_registry_enabled_default = False",
            sensor_source,
        )


if __name__ == "__main__":
    unittest.main()
