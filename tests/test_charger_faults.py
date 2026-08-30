"""Tests for persistent Growatt charger fault events."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
    / "charger_faults.py"
)
SPEC = importlib.util.spec_from_file_location(
    "growatt_thor_charger_faults_test_target",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
faults = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = faults
SPEC.loader.exec_module(faults)


class ChargerFaultTest(unittest.TestCase):
    """Verify classification, merging, and persistence."""

    def test_merges_captured_emergency_stop_messages(self):
        status_fault = faults.fault_from_status_notification(
            "2026-08-30T08:00:52.461000+00:00",
            1,
            "OtherError",
            {
                "info": "Emergency stop press,or emergency stop is broken",
                "vendor_id": "Growatt",
                "vendor_error_code": (
                    "Emergency stop press,or emergency stop is broken"
                ),
            },
        )
        merged = faults.fault_from_data_transfer(
            "2026-08-30T08:00:52.552000+00:00",
            "Growatt",
            "connectorId=1&time=2026-08-30T10:00:51+02:00&errcode=100&"
            "info=Emergency stop press,or emergency stop is broken",
            status_fault,
        )

        self.assertEqual(merged.category, "emergency_stop")
        self.assertEqual(merged.ocpp_error_code, "OtherError")
        self.assertEqual(merged.growatt_error_code, "100")
        self.assertEqual(merged.reported_at, "2026-08-30T10:00:51+02:00")
        self.assertEqual(
            merged.sources,
            ("StatusNotification", "DataTransfer/faultmessage"),
        )

    def test_power_meter_failure_has_its_own_category(self):
        fault = faults.fault_from_status_notification(
            "2026-08-30T06:43:45+00:00",
            1,
            "PowerMeterFailure",
            {"info": "485 Fault"},
        )
        self.assertEqual(fault.category, "power_meter_failure")

    def test_unrelated_faultmessage_does_not_merge_old_event(self):
        previous = faults.ChargerFault(
            category="emergency_stop",
            observed_at="2026-08-30T08:00:00+00:00",
            connector_id=1,
            sources=("StatusNotification",),
        )
        current = faults.fault_from_data_transfer(
            "2026-08-30T08:05:00+00:00",
            "Growatt",
            "connectorId=1&errcode=100&info=Emergency stop",
            previous,
        )
        self.assertEqual(current.sources, ("DataTransfer/faultmessage",))
        self.assertEqual(current.observed_at, "2026-08-30T08:05:00+00:00")

    def test_round_trips_persistent_state(self):
        original = faults.ChargerFault(
            category="emergency_stop",
            observed_at="2026-08-30T08:00:52+00:00",
            connector_id=1,
            ocpp_error_code="OtherError",
            growatt_error_code="100",
            sources=("StatusNotification", "DataTransfer/faultmessage"),
        )
        self.assertEqual(
            faults.ChargerFault.from_dict(original.as_dict()),
            original,
        )


if __name__ == "__main__":
    unittest.main()
