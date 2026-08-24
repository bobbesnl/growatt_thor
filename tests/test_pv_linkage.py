"""Tests for compound Growatt PV Linkage controls."""
from __future__ import annotations

from datetime import datetime, time, timezone
import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
    / "pv_linkage.py"
)
SPEC = importlib.util.spec_from_file_location(
    "growatt_thor_pv_linkage_test_target",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
pv = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pv
SPEC.loader.exec_module(pv)


class PvLinkageControlTest(unittest.TestCase):
    """Verify captured Manual and Smart Boost payloads."""

    def test_parses_first_reported_manual_period(self):
        self.assertEqual(
            pv.parse_manual_period("1&time1=00:00-23:59"),
            (time(0, 0), time(23, 59)),
        )
        self.assertIsNone(pv.parse_manual_period("1&broken"))

    def test_disabled_boost_is_one_configuration_write(self):
        self.assertEqual(
            pv.build_pv_linkage_writes(
                pv.PvLinkageDraft(pv.PvBoostMode.DISABLED),
                now=datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc),
            ),
            (pv.ConfigurationWrite("G_SolarBoost", "1&Disable"),),
        )

    def test_manual_boost_writes_mode_then_period(self):
        writes = pv.build_pv_linkage_writes(
            pv.PvLinkageDraft(
                pv.PvBoostMode.MANUAL,
                manual_start=time(0, 0),
                manual_end=time(23, 59),
            ),
            now=datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            writes,
            (
                pv.ConfigurationWrite("G_SolarBoost", "1&ManualBoost"),
                pv.ConfigurationWrite(
                    "G_PeriodTime",
                    "1&time1=00:00-23:59",
                ),
            ),
        )

    def test_smart_boost_uses_next_finish_and_dot_decimal(self):
        writes = pv.build_pv_linkage_writes(
            pv.PvLinkageDraft(
                pv.PvBoostMode.SMART,
                smart_finish=time(10, 34),
                smart_target_energy_kwh=4.2,
            ),
            now=datetime(2026, 8, 24, 11, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            writes,
            (
                pv.ConfigurationWrite("G_SolarBoost", "1&SmartBoost"),
                pv.DataTransferWrite(
                    "Growatt",
                    "solar_target_data",
                    "connectorid=1&contime=2026-08-25 10:34&energy=4.2",
                ),
            ),
        )

    def test_selected_mode_requires_its_dependent_fields(self):
        self.assertEqual(
            pv.draft_validation_errors(
                pv.PvLinkageDraft(pv.PvBoostMode.MANUAL)
            ),
            ("manual_start_required", "manual_end_required"),
        )
        self.assertEqual(
            pv.draft_validation_errors(
                pv.PvLinkageDraft(
                    pv.PvBoostMode.SMART,
                    smart_finish=time(10, 0),
                    smart_target_energy_kwh=0,
                )
            ),
            ("smart_target_energy_required",),
        )

    def test_draft_matches_only_readable_reported_state(self):
        disabled = pv.PvLinkageDraft(pv.PvBoostMode.DISABLED)
        self.assertTrue(
            pv.draft_matches_reported(
                disabled,
                reported_mode="disabled",
                reported_period="1&time1=12:00-13:00",
            )
        )

        manual = pv.PvLinkageDraft(
            pv.PvBoostMode.MANUAL,
            manual_start=time(12, 0),
            manual_end=time(13, 0),
        )
        self.assertTrue(
            pv.draft_matches_reported(
                manual,
                reported_mode="manual",
                reported_period="1&time1=12:00-13:00",
            )
        )
        self.assertFalse(
            pv.draft_matches_reported(
                manual,
                reported_mode="manual",
                reported_period="1&time1=00:00-05:00",
            )
        )

        smart = pv.PvLinkageDraft(
            pv.PvBoostMode.SMART,
            smart_finish=time(10, 0),
            smart_target_energy_kwh=4,
        )
        self.assertFalse(
            pv.draft_matches_reported(
                smart,
                reported_mode="smart",
                reported_period=None,
            )
        )


if __name__ == "__main__":
    unittest.main()
