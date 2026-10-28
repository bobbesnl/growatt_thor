"""Tests for Home Assistant OCPP status normalization."""

from __future__ import annotations

import unittest
from enum import Enum

from tests.support import PACKAGE_PATH, load_package_module, register_package

MODULE_PATH = PACKAGE_PATH / "ocpp/status.py"
PACKAGE_NAME = "growatt_thor_ocpp_status_test_target"
package = register_package(PACKAGE_NAME)
ocpp_status = load_package_module(f"{PACKAGE_NAME}.ocpp.status", MODULE_PATH)


class Status(Enum):
    """Representative OCPP enum values."""

    SUSPENDED_EVSE = "SuspendedEVSE"


class OcppStatusTest(unittest.TestCase):
    """Verify OCPP values map to translation-safe entity states."""

    def test_all_wire_statuses_map_to_declared_options(self):
        wire_values = (
            "Available",
            "Preparing",
            "Charging",
            "SuspendedEVSE",
            "SuspendedEV",
            "Finishing",
            "Reserved",
            "Unavailable",
            "Faulted",
            "Idle",
        )

        self.assertEqual(
            tuple(ocpp_status.normalize_ocpp_status(value) for value in wire_values),
            ocpp_status.OCPP_STATUS_OPTIONS,
        )

    def test_enum_and_canonical_values_are_supported(self):
        self.assertEqual(
            ocpp_status.normalize_ocpp_status(Status.SUSPENDED_EVSE),
            "suspended_evse",
        )
        self.assertEqual(
            ocpp_status.normalize_ocpp_status("suspended_ev"),
            "suspended_ev",
        )

    def test_status_groups_accept_case_and_separator_variants(self):
        for value in ("Charging", "charging", "CHARGING"):
            self.assertIn(ocpp_status.normalize_ocpp_status(value), ocpp_status.LIVE_POWER_STATUSES)
        for value in ("SuspendedEV", "SUSPENDED_EV", "suspended_evse"):
            self.assertIn(
                ocpp_status.normalize_ocpp_status(value), ocpp_status.ENERGY_SESSION_STATUSES
            )

    def test_missing_or_unknown_status_is_unavailable(self):
        self.assertIsNone(ocpp_status.normalize_ocpp_status(None))
        self.assertIsNone(ocpp_status.normalize_ocpp_status("FutureStatus"))


if __name__ == "__main__":
    unittest.main()
