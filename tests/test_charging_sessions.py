"""Tests for correlation of OCPP and Growatt charging session data."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


COMPONENT_PATH = (
    Path(__file__).parents[1] / "custom_components" / "growatt_thor"
)


def _load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, COMPONENT_PATH / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


session_records = _load_module(
    "growatt_thor_session_records_for_session_test",
    "session_records.py",
)
charging_sessions = _load_module(
    "growatt_thor_charging_sessions_test_target",
    "charging_sessions.py",
)


def _transaction(transaction_id: int = 7):
    return {
        "start": {
            "received_at": "2026-08-24T10:00:01Z",
            "request": {
                "connector_id": 1,
                "id_tag": "private",
                "meter_start": 0,
                "timestamp": "2026-08-24T10:00:00Z",
            },
            "response": {"transaction_id": transaction_id},
        },
        "stop": {
            "received_at": "2026-08-24T10:30:01Z",
            "request": {
                "transaction_id": transaction_id,
                "meter_stop": 412,
                "reason": "EVDisconnected",
                "timestamp": "2026-08-24T10:30:00Z",
            },
        },
    }


def _record_snapshot(transaction_id: int = 7, *, received_at: str = "12:00:00"):
    record = session_records.parse_growatt_session_record(
        "currentrecord",
        (
            f"id=346&connectorId=1&transactionId={transaction_id}&"
            "plugtime=2026-08-24 09:55:00&starttime=2026-08-24 10:00:00&"
            "endtime=2026-08-24 10:30:00&unplugtime=2026-08-24 10:31:00&"
            "costenergy=412&costmoney=9&chargemode=3&workmode=0"
        ),
    )
    return {
        "received_at": f"2026-08-24T{received_at}Z",
        "record": record,
    }


class UnifiedChargingSessionTest(unittest.TestCase):
    """Verify strict correlation and source-specific values."""

    def test_matches_ocpp_transaction_and_growatt_record(self):
        session = charging_sessions.build_unified_session(
            _transaction(),
            meter_values={
                "transaction_id": 7,
                "meter_values": [
                    {
                        "sampled_values": [
                            {
                                "measurand": "Energy.Active.Import.Register",
                                "numeric_value": 0.412,
                                "unit": "kWh",
                            }
                        ]
                    }
                ],
            },
            session_records=(_record_snapshot(),),
        )

        self.assertEqual(session["correlation"]["status"], "matched")
        self.assertEqual(
            session["correlation"]["sources"],
            ["ocpp", "currentrecord"],
        )
        self.assertTrue(session["correlation"]["transaction_id_match"])
        self.assertEqual(session["identity"]["ocpp_transaction_id"], "7")
        self.assertEqual(session["identity"]["growatt_transaction_id"], "7")
        self.assertEqual(session["identity"]["connector_id"], "1")
        self.assertEqual(session["metering"]["ocpp_meter_delta_wh"], 412.0)
        self.assertEqual(session["metering"]["latest_meter_value_wh"], 412.0)
        self.assertEqual(session["metering"]["growatt_energy_wh"], 412.0)
        self.assertEqual(session["metering"]["energy_delta_wh"], 0.0)
        self.assertEqual(session["billing"]["growatt_cost"], 0.09)
        self.assertEqual(session["modes"]["growatt_charge_mode"], "3")
        self.assertEqual(session["stop_reason"], "EVDisconnected")

    def test_does_not_merge_different_transaction_ids(self):
        session = charging_sessions.build_unified_session(
            _transaction(transaction_id=7),
            session_records=(_record_snapshot(transaction_id=8),),
        )

        self.assertEqual(session["correlation"]["status"], "ocpp_only")
        self.assertEqual(session["correlation"]["sources"], ["ocpp"])
        self.assertIsNone(session["identity"]["growatt_transaction_id"])
        self.assertIsNone(session["metering"]["growatt_energy_wh"])

    def test_does_not_merge_reused_transaction_id_with_older_record(self):
        older_record = _record_snapshot(transaction_id=7)
        older_record["received_at"] = "2026-08-23T12:00:00Z"

        session = charging_sessions.build_unified_session(
            _transaction(transaction_id=7),
            session_records=(older_record,),
        )

        self.assertEqual(session["correlation"]["status"], "ocpp_only")
        self.assertEqual(session["identity"]["ocpp_transaction_id"], "7")
        self.assertIsNone(session["identity"]["growatt_transaction_id"])

    def test_retains_latest_growatt_session_without_ocpp_transaction(self):
        session = charging_sessions.build_unified_session(
            None,
            session_records=(
                _record_snapshot(transaction_id=7, received_at="11:00:00"),
                _record_snapshot(transaction_id=8, received_at="12:00:00"),
            ),
        )

        self.assertEqual(session["correlation"]["status"], "growatt_only")
        self.assertEqual(session["correlation"]["sources"], ["currentrecord"])
        self.assertEqual(
            session["identity"]["transaction_scope"],
            "external_or_unknown",
        )
        self.assertEqual(session["identity"]["growatt_transaction_id"], "8")

    def test_uses_latest_meter_energy_for_active_ocpp_session(self):
        transaction = _transaction()
        transaction.pop("stop")
        session = charging_sessions.build_unified_session(
            transaction,
            meter_values={
                "transaction_id": "7",
                "meter_values": [
                    {
                        "sampled_values": [
                            {
                                "measurand": "Energy.Active.Import.Register",
                                "numeric_value": 125,
                                "unit": "Wh",
                            }
                        ]
                    }
                ],
            },
        )

        self.assertEqual(session["correlation"]["status"], "ocpp_only")
        self.assertEqual(session["metering"]["latest_meter_value_wh"], 125.0)
        self.assertIsNone(session["metering"]["ocpp_meter_delta_wh"])

    def test_does_not_use_meter_value_from_later_reused_transaction_id(self):
        session = charging_sessions.build_unified_session(
            _transaction(transaction_id=7),
            meter_values={
                "received_at": "2026-08-24T11:00:00Z",
                "transaction_id": 7,
                "meter_values": [
                    {
                        "sampled_values": [
                            {
                                "measurand": "Energy.Active.Import.Register",
                                "numeric_value": 99,
                                "unit": "Wh",
                            }
                        ]
                    }
                ],
            },
        )

        self.assertIsNone(session["metering"]["latest_meter_value_wh"])


if __name__ == "__main__":
    unittest.main()
