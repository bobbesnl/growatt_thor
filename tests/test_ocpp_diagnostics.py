"""Tests for retained and redacted OCPP diagnostics."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
    / "ocpp_diagnostics.py"
)
SPEC = importlib.util.spec_from_file_location(
    "growatt_thor_ocpp_diagnostics_test_target",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
ocpp_diagnostics = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ocpp_diagnostics
SPEC.loader.exec_module(ocpp_diagnostics)


class Status(Enum):
    """Representative OCPP enum."""

    AVAILABLE = "Available"


class OcppDiagnosticsTest(unittest.TestCase):
    """Verify snapshot normalization and diagnostics redaction."""

    def test_snapshot_preserves_nested_payload_fields(self):
        snapshot = ocpp_diagnostics.create_ocpp_snapshot(
            "2026-08-23T20:00:00Z",
            {
                "status": Status.AVAILABLE,
                "timestamp": datetime(2026, 8, 23, tzinfo=timezone.utc),
                "transaction_data": [{"sampled_value": ("1", "2")}],
                "vendor_extension": {"code": 42},
            },
        )

        self.assertEqual(snapshot["received_at"], "2026-08-23T20:00:00Z")
        self.assertEqual(snapshot["request"]["status"], "Available")
        self.assertEqual(
            snapshot["request"]["timestamp"],
            "2026-08-23T00:00:00+00:00",
        )
        self.assertEqual(
            snapshot["request"]["transaction_data"],
            [{"sampled_value": ["1", "2"]}],
        )
        self.assertEqual(snapshot["request"]["vendor_extension"], {"code": 42})

    def test_redaction_keeps_structure_and_diagnostic_fields(self):
        diagnostics = {
            "boot": {
                "request": {
                    "charge_point_model": "THOR_22AS",
                    "charge_point_serial_number": "serial",
                    "firmware_version": "2.2.16",
                    "iccid": "sim-card",
                }
            },
            "transaction": {
                "request": {
                    "id_tag": "secret-tag",
                    "meter_stop": 1234,
                    "reason": "EVDisconnected",
                    "transaction_data": [
                        {"idTag": "nested-tag", "vendorErrorCode": "E42"}
                    ],
                }
            },
        }

        redacted = ocpp_diagnostics.redact_ocpp_data(diagnostics)

        self.assertEqual(
            redacted["boot"]["request"]["charge_point_serial_number"],
            ocpp_diagnostics.REDACTED,
        )
        self.assertEqual(
            redacted["boot"]["request"]["iccid"],
            ocpp_diagnostics.REDACTED,
        )
        self.assertEqual(
            redacted["transaction"]["request"]["id_tag"],
            ocpp_diagnostics.REDACTED,
        )
        self.assertEqual(
            redacted["transaction"]["request"]["transaction_data"][0]["idTag"],
            ocpp_diagnostics.REDACTED,
        )
        self.assertEqual(redacted["boot"]["request"]["firmware_version"], "2.2.16")
        self.assertEqual(redacted["transaction"]["request"]["meter_stop"], 1234)
        self.assertEqual(
            redacted["transaction"]["request"]["transaction_data"][0][
                "vendorErrorCode"
            ],
            "E42",
        )


if __name__ == "__main__":
    unittest.main()
