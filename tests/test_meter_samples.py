"""Tests for lossless OCPP MeterValues parsing."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
    / "ocpp/meter_samples.py"
)
SPEC = importlib.util.spec_from_file_location(
    "growatt_thor_meter_samples_test_target",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
meter_samples = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = meter_samples
SPEC.loader.exec_module(meter_samples)


class Context(Enum):
    """Representative OCPP context enum."""

    PERIODIC = "Sample.Periodic"


@dataclass
class Sample:
    """Representative OCPP SampledValue model."""

    value: str
    measurand: str
    phase: str | None = None
    context: Context | None = None
    vendor_extension: object | None = None


@dataclass
class Entry:
    """Representative OCPP MeterValue model."""

    timestamp: str
    sampled_value: list[Sample]


class MeterSamplesTest(unittest.TestCase):
    """Verify lossless parsing and normalized accessors."""

    def test_local_wallbox_timestamps_use_installation_zone_and_preserve_raw(self):
        for raw, expected in (
            ("2026-10-02T16:52:49", "2026-10-02T14:52:49Z"),
            ("2026-01-02T16:52:49", "2026-01-02T15:52:49Z"),
            ("2026-10-02T16:52:49+02:00", "2026-10-02T14:52:49Z"),
            ("2026-10-02T14:52:49Z", "2026-10-02T14:52:49Z"),
            ("2026-10-25T02:30:00+02:00", "2026-10-25T00:30:00Z"),
            ("2026-10-25T02:30:00+01:00", "2026-10-25T01:30:00Z"),
        ):
            with self.subTest(raw=raw):
                entry = meter_samples.parse_meter_values(
                    {"timestamp": raw, "sampledValue": []}, time_zone="Europe/Berlin",
                )[0]
                self.assertEqual(entry.timestamp, expected)
                self.assertEqual(entry.raw["timestamp"], raw)

    def test_ambiguous_nonexistent_and_invalid_times_are_not_guessed(self):
        for raw, zone in (
            ("2026-10-25T02:30:00", "Europe/Berlin"),
            ("2026-03-29T02:30:00", "Europe/Berlin"),
            ("2026-10-02T16:52:49", None),
            ("2026-10-02T16:52:49", "Invalid/Zone"),
            ("2026-10-02", "Europe/Berlin"),
            ("bad", "Europe/Berlin"),
            (None, "Europe/Berlin"),
        ):
            with self.subTest(raw=raw, zone=zone):
                self.assertIsNone(meter_samples.normalize_meter_timestamp(raw, zone))

    def test_parses_object_models_and_preserves_extensions(self):
        parsed = meter_samples.parse_meter_values(
            [
                Entry(
                    timestamp="2026-08-24T10:00:00Z",
                    sampled_value=[
                        Sample(
                            value="16.25",
                            measurand="Current.Import",
                            phase="L1",
                            context=Context.PERIODIC,
                            vendor_extension={"quality": "measured"},
                        )
                    ],
                )
            ]
        )

        self.assertEqual(len(parsed), 1)
        sample = parsed[0].samples[0]
        self.assertEqual(sample.numeric_value, 16.25)
        self.assertEqual(sample.phase, "L1")
        self.assertEqual(sample.context, "Sample.Periodic")
        self.assertEqual(
            sample.raw["vendor_extension"],
            {"quality": "measured"},
        )

    def test_accepts_camel_case_payload_and_unknown_measurand(self):
        parsed = meter_samples.parse_meter_values(
            {
                "timestamp": "2026-08-24T10:01:00Z",
                "sampledValue": [
                    {
                        "value": "42",
                        "measurand": "Vendor.Custom.Measurement",
                        "unit": "Percent",
                        "vendorCode": "X1",
                    }
                ],
                "vendorBatch": 7,
            }
        )

        self.assertEqual(parsed[0].samples[0].numeric_value, 42.0)
        self.assertEqual(
            parsed[0].samples[0].measurand,
            "Vendor.Custom.Measurement",
        )
        self.assertEqual(parsed[0].samples[0].raw["vendorCode"], "X1")
        self.assertEqual(parsed[0].raw["vendorBatch"], 7)

    def test_invalid_value_remains_available_for_diagnostics(self):
        parsed = meter_samples.parse_meter_values(
            [{"sampled_value": [{"value": "not-a-number", "phase": "L2"}]}]
        )

        sample = parsed[0].samples[0]
        self.assertIsNone(sample.numeric_value)
        self.assertEqual(sample.raw_value, "not-a-number")
        self.assertEqual(
            sample.measurand,
            meter_samples.DEFAULT_MEASURAND,
        )
        self.assertEqual(sample.as_dict()["raw"]["value"], "not-a-number")

    def test_empty_sample_collection_is_retained(self):
        parsed = meter_samples.parse_meter_values(
            [{"timestamp": "2026-08-24T10:02:00Z", "sampledValue": []}]
        )

        self.assertEqual(parsed[0].timestamp, "2026-08-24T10:02:00Z")
        self.assertEqual(parsed[0].samples, ())
        self.assertEqual(parsed[0].raw["sampledValue"], [])

    def test_builds_total_power_curve_point_with_unit_conversion(self):
        entry = meter_samples.parse_meter_values({
            "timestamp": "2026-09-12T10:00:00Z",
            "sampledValue": [
                {"value": "3.2", "measurand": "Power.Active.Import", "unit": "kW", "phase": "L1"},
                {"value": "3100", "measurand": "Power.Active.Import", "unit": "W", "phase": "L2"},
            ],
        })[0]
        self.assertEqual(
            meter_samples.charging_power_curve_point(entry),
            ["2026-09-12T10:00:00Z", 6300.0],
        )

    def test_curve_point_does_not_invent_missing_power(self):
        entry = meter_samples.parse_meter_values({
            "timestamp": "2026-09-12T10:00:00Z",
            "sampledValue": [{"value": "12", "measurand": "Current.Import", "unit": "A"}],
        })[0]
        self.assertIsNone(meter_samples.charging_power_curve_point(entry))


if __name__ == "__main__":
    unittest.main()
