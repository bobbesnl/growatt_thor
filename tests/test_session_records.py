"""Tests for structured Growatt currentrecord and frozenrecord parsing."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
    / "session_records.py"
)
SPEC = importlib.util.spec_from_file_location(
    "growatt_thor_session_records_test_target",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
session_records = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = session_records
SPEC.loader.exec_module(session_records)


OBSERVED_PAYLOAD = (
    "id=346&connectorId=1&chargemode=3&plugtime=2025-08-24 11:47:21&"
    "unplugtime=2025-08-25 10:04:23&starttime=2025-08-25 09:56:06&"
    "endtime=2025-08-25 10:04:23&costenergy=211&costmoney=4&"
    "transactionId=1622129&workmode=3"
)


class GrowattSessionRecordTest(unittest.TestCase):
    """Verify normalized values and lossless field retention."""

    def test_parses_observed_record(self):
        record = session_records.parse_growatt_session_record(
            "currentrecord",
            OBSERVED_PAYLOAD,
        )

        self.assertEqual(record.message_id, "currentrecord")
        self.assertEqual(record.connector_id, "1")
        self.assertEqual(record.transaction_id, "1622129")
        self.assertEqual(record.energy_wh, 211.0)
        self.assertEqual(record.energy_kwh, 0.211)
        self.assertEqual(record.cost_minor, 4.0)
        self.assertEqual(record.cost, 0.04)
        self.assertEqual(record.duration_minutes, 8.3)
        self.assertEqual(
            record.dedup_key,
            ("1622129", "2025-08-25 10:04:23"),
        )
        self.assertEqual(record.parse_errors, ())

    def test_preserves_blank_duplicate_and_unknown_fields(self):
        payload = "transactionId=12&custom=&custom=second&costenergy=0"
        record = session_records.parse_growatt_session_record(
            "frozenrecord",
            payload,
        )

        self.assertEqual(record.raw_payload, payload)
        self.assertEqual(record.fields["custom"], ("", "second"))
        self.assertEqual(record.energy_kwh, 0.0)
        self.assertEqual(record.as_dict()["unknown_fields"], ["custom"])

    def test_invalid_values_remain_visible(self):
        record = session_records.parse_growatt_session_record(
            "currentrecord",
            "costenergy=broken&starttime=not-a-date&transactionId=42",
        )

        self.assertIsNone(record.energy_kwh)
        self.assertIsNone(record.duration_minutes)
        self.assertEqual(len(record.parse_errors), 2)
        self.assertEqual(record.first("costenergy"), "broken")

    def test_diagnostics_redact_raw_and_unknown_values(self):
        record = session_records.parse_growatt_session_record(
            "frozenrecord",
            OBSERVED_PAYLOAD + "&futureIdentifier=private-value",
        )
        diagnostics = session_records.session_record_diagnostics(
            {"received_at": "2026-08-24T12:00:00+00:00", "record": record}
        )

        self.assertEqual(
            diagnostics["record"]["raw_payload"],
            session_records.REDACTED,
        )
        self.assertEqual(
            diagnostics["record"]["fields"]["futureIdentifier"],
            [session_records.REDACTED],
        )
        self.assertEqual(
            diagnostics["record"]["fields"]["transactionId"],
            ["1622129"],
        )

    def test_rejects_non_session_message_id(self):
        with self.assertRaises(ValueError):
            session_records.parse_growatt_session_record(
                "get_external_meterval",
                "used=1",
            )


class GrowattSessionModeTest(unittest.TestCase):
    """Verify stable entity states for vendor session mode codes."""

    def test_charge_mode_codes(self):
        for raw_value, expected in (
            ("1", "home_assistant_rfid"),
            ("2", "rfid_only"),
            ("3", "plug_and_charge"),
            ("future", session_records.UNKNOWN_MODE),
        ):
            with self.subTest(raw_value=raw_value):
                self.assertEqual(
                    session_records.normalize_session_charge_mode(raw_value),
                    expected,
                )

    def test_only_confirmed_numeric_work_mode_is_mapped(self):
        self.assertEqual(
            session_records.normalize_session_work_mode("0"),
            "fast",
        )
        self.assertEqual(
            session_records.normalize_session_work_mode("3"),
            session_records.UNKNOWN_MODE,
        )

    def test_empty_modes_remain_unavailable(self):
        self.assertIsNone(session_records.normalize_session_charge_mode(""))
        self.assertIsNone(session_records.normalize_session_work_mode(None))


if __name__ == "__main__":
    unittest.main()
