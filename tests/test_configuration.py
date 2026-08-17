"""Tests for the standalone configuration registry."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
    / "configuration.py"
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


if __name__ == "__main__":
    unittest.main()
