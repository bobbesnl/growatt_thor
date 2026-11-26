"""Tests for the bounded session-card CSV projection."""

import csv
import tempfile
import unittest
from importlib import import_module
from pathlib import Path

from tests.support import PACKAGE_PATH, load_package_module, register_package

COMPONENT = PACKAGE_PATH
PACKAGE_NAME = "thor_session_dashboard_test"
PACKAGE = register_package(PACKAGE_NAME)


def load(name, filename):
    return load_package_module(name, filename)


load(f"{PACKAGE_NAME}.sessions.identity", "sessions/identity.py")
session_csv = load(f"{PACKAGE_NAME}.sessions.csv", "sessions/csv.py")
archive_summary = import_module(session_csv.__package__ + ".archive_summary")
history_rows = import_module(session_csv.__package__ + ".history_rows")
history_store = import_module(session_csv.__package__ + ".history_store")
history_views = import_module(session_csv.__package__ + ".history_views")


class SessionDashboardTest(unittest.TestCase):
    def test_summary_and_detail_expose_saved_names_without_inventing_legacy_names(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=history_rows.SESSION_LOG_HEADERS)
                writer.writeheader()
                writer.writerow(
                    {
                        "session_id": "named",
                        "session_source": "home_assistant",
                        "start_time": "2026-10-27T10:00:00Z",
                        "authorized_identifier": "00AbC",
                        "authorized_alias": "Family car",
                    }
                )
                writer.writerow(
                    {
                        "session_id": "unnamed",
                        "session_source": "home_assistant",
                        "start_time": "2026-10-26T10:00:00Z",
                        "authorized_identifier": "OLD",
                    }
                )
            history = history_views.dashboard_session_data(path)
            named, unnamed = history["items"]
            self.assertEqual(named["authorized_identifier"], "00AbC")
            self.assertEqual(named["authorized_alias"], "Family car")
            self.assertEqual(unnamed["authorized_identifier"], "OLD")
            self.assertIsNone(unnamed["authorized_alias"])
            detail = history_views.session_detail_data(path, "named")
            self.assertEqual(detail["authorized_alias"], "Family car")
            self.assertEqual(detail["authorized_identifier"], "00AbC")

    def test_missing_log_has_known_zero_totals_and_unknown_green_energy(self):
        with tempfile.TemporaryDirectory() as directory:
            data = history_views.dashboard_session_data(Path(directory) / "missing.csv")
        self.assertEqual(data["items"], [])
        self.assertEqual(data["total_energy_kwh"], 0.0)
        self.assertIsNone(data["total_green_energy_kwh"])

    def test_history_is_bounded_sorted_and_keeps_identifier(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.csv"
            with path.open("w", newline="", encoding="utf-8") as target:
                writer = csv.DictWriter(target, fieldnames=history_rows.SESSION_LOG_HEADERS)
                writer.writeheader()
                writer.writerow(
                    {
                        "start_time": "2026-09-10 10:00:00",
                        "energy_kwh": "2.5",
                        "cost": "0.70",
                        "authorized_identifier": "RFID-A",
                    }
                )
                writer.writerow(
                    {
                        "start_time": "2026-09-11 10:00:00",
                        "energy_kwh": "3.5",
                        "cost": "1.10",
                        "authorized_identifier": "freevenID",
                        "power_curve": '[["2026-09-11T10:00:00Z",7200],["bad",-1]]',
                    }
                )
            data = history_views.dashboard_session_data(path, limit=1)
        self.assertEqual(data["total_count"], 2)
        self.assertEqual(data["total_energy_kwh"], 6.0)
        self.assertEqual(data["items"][0]["authorized_identifier"], "freevenID")
        self.assertFalse(data["items"][0]["active"])
        self.assertIsNone(data["items"][0]["green_energy_kwh"])
        self.assertEqual(data["items"][0]["power_curve"], [["2026-09-11T10:00:00Z", 7200.0]])


class MultiChargerHistoryTest(unittest.TestCase):
    def test_history_totals_and_details_are_scoped_before_limiting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.csv"
            for name, energy in [("left", 2), ("right", 7)]:
                session_csv.append_session_row(
                    path,
                    {
                        "source_instance_id": name,
                        "charger_id": "THOR-" + name,
                        "session_id": name,
                        "session_source": "home_assistant",
                        "start_time": "2026-10-21T10:00:00Z",
                        "energy_kwh": energy,
                    },
                )
            left = history_views.dashboard_session_data(path, source_instance_id="left", limit=1)
            self.assertEqual(left["total_energy_kwh"], 2)
            self.assertEqual([item["session_id"] for item in left["items"]], ["left"])
            self.assertIsNone(
                history_views.session_detail_data(path, "right", source_instance_id="left")
            )
            self.assertEqual(
                history_views.session_detail_data(path, "right", source_instance_id="right")[
                    "energy_kwh"
                ],
                7,
            )
            self.assertEqual(history_views.dashboard_session_data(path)["total_energy_kwh"], 9)

    def test_legacy_rows_require_matching_charger_and_explicit_owner_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.csv"
            for name, owner, energy in [("legacy", "", 2), ("owned", "right", 7)]:
                session_csv.append_session_row(
                    path,
                    {
                        "source_instance_id": owner,
                        "charger_id": "THOR",
                        "session_id": name,
                        "session_source": "home_assistant",
                        "start_time": "2026-10-21T10:00:00Z",
                        "energy_kwh": energy,
                    },
                )
            self.assertEqual(
                history_views.dashboard_session_data(path, source_instance_id="left")[
                    "total_count"
                ],
                0,
            )
            self.assertEqual(
                history_views.dashboard_session_data(
                    path, source_instance_id="left", charge_point_id="THOR"
                )["total_energy_kwh"],
                2,
            )

    def test_retention_preserves_separate_totals(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.csv"
            for name, energy in [("left", 2), ("right", 7)]:
                session_csv.append_session_row(
                    path,
                    {
                        "source_instance_id": name,
                        "charger_id": "THOR-" + name,
                        "session_id": name,
                        "session_source": "home_assistant",
                        "start_time": "2020-01-01T10:00:00Z",
                        "energy_kwh": energy,
                    },
                )
            session_csv.enforce_session_retention(path)
            for name, energy in [("left", 2), ("right", 7)]:
                data = history_views.dashboard_session_data(path, source_instance_id=name)
                self.assertEqual(data["items"], [])
                self.assertEqual(data["total_energy_kwh"], energy)
                self.assertEqual(data["total_count"], 1)

    def test_unlabelled_archive_is_inherited_only_by_the_original_single_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.csv"
            archive = archive_summary.empty_archive_summary()
            archive.update(total_energy_kwh=12.5, total_count=3)
            history_store.write_archive_summary(path, archive)
            inherited = history_views.dashboard_session_data(
                path, source_instance_id="original", include_unassigned_archive=True
            )
            other = history_views.dashboard_session_data(path, source_instance_id="new")
            self.assertEqual(inherited["total_energy_kwh"], 12.5)
            self.assertEqual(inherited["total_count"], 3)
            self.assertEqual(other["total_count"], 0)


if __name__ == "__main__":
    unittest.main()


class PartialGreenSummaryTest(unittest.TestCase):
    def write_rows(self, path, rows):
        import json

        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=history_rows.SESSION_LOG_HEADERS)
            writer.writeheader()
            for index, row in enumerate(rows):
                value = {
                    "session_id": f"session-{index}",
                    "session_source": "home_assistant",
                    "source_instance_id": "left",
                    "start_time": "2026-10-24 10:00:00",
                    "energy_kwh": 10,
                    "cost": 1,
                    **row,
                }
                if isinstance(value.get("source_energy_kwh"), dict):
                    value["source_energy_kwh"] = json.dumps(value["source_energy_kwh"])
                writer.writerow(value)

    def sources(self, solar=6, grid=3, battery=0.9, unknown=0.1):
        return {
            "direct_solar": solar,
            "direct_grid": grid,
            "battery_unknown": battery,
            "unknown": unknown,
        }

    def test_partial_sessions_contribute_solar_without_rewriting_strict_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.csv"
            self.write_rows(
                path,
                [
                    {"source_energy_kwh": self.sources(), "accounting_coverage": 0.99},
                    {"source_energy_kwh": self.sources(solar=0, grid=0, battery=9, unknown=1)},
                    {"green_energy_kwh": 2},
                ],
            )
            before = path.read_bytes()
            data = history_views.dashboard_session_data(path, limit=1)
            self.assertEqual(data["total_green_energy_kwh"], 8)
            self.assertTrue(data["total_green_partial"])
            self.assertIsNone(data["items"][0]["green_energy_kwh"])
            self.assertEqual(path.read_bytes(), before)

    def test_full_zero_unknown_and_invalid_sources_keep_distinct_meanings(self):
        cases = [
            ({"green_energy_kwh": 0}, 0, False),
            (
                {"source_energy_kwh": self.sources(solar=6, grid=3, battery=1, unknown=0)},
                6,
                False,
            ),
            (
                {"source_energy_kwh": self.sources(solar=0, grid=0, battery=10, unknown=0)},
                0,
                False,
            ),
            (
                {"source_energy_kwh": self.sources(solar=0, grid=0, battery=0, unknown=10)},
                None,
                True,
            ),
            ({}, None, True),
            ({"source_energy_kwh": self.sources(solar=20)}, None, True),
            ({"source_energy_kwh": self.sources(solar=-1)}, None, True),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.csv"
            for row, expected, partial in cases:
                with self.subTest(row=row):
                    self.write_rows(path, [row])
                    data = history_views.dashboard_session_data(path)
                    self.assertEqual(data["total_green_energy_kwh"], expected)
                    self.assertEqual(data["total_green_partial"], partial)
            self.write_rows(path, [{"green_energy_kwh": 2}, {}])
            data = history_views.dashboard_session_data(path)
            self.assertEqual(data["total_green_energy_kwh"], 2)
            self.assertTrue(data["total_green_partial"])

    def test_retention_restart_and_entry_scope_preserve_partial_totals(self):
        from datetime import date

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.csv"
            self.write_rows(
                path,
                [
                    {"source_energy_kwh": self.sources()},
                    {"source_instance_id": "right", "green_energy_kwh": 2},
                ],
            )
            self.assertEqual(
                session_csv.enforce_session_retention(path, today=date(2026, 10, 25), max_rows=0),
                2,
            )
            for owner, expected, partial in [("left", 6, True), ("right", 2, False)]:
                with self.subTest(owner=owner):
                    data = history_views.dashboard_session_data(path, source_instance_id=owner)
                    self.assertEqual(data["items"], [])
                    self.assertEqual(data["total_green_energy_kwh"], expected)
                    self.assertEqual(data["total_green_partial"], partial)
            self.assertEqual(
                session_csv.enforce_session_retention(path, today=date(2026, 10, 25), max_rows=0),
                0,
            )
            data = history_views.dashboard_session_data(path)
            self.assertEqual(data["total_green_energy_kwh"], 8)
            self.assertTrue(data["total_green_partial"])
            path.unlink()
            self.assertEqual(
                history_views.dashboard_session_data(path)["total_green_energy_kwh"], 8
            )
            self.assertTrue(history_views.dashboard_session_data(path)["total_green_partial"])

    def test_old_archives_remain_qualified_without_inventing_pruned_solar(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.csv"
            summary = archive_summary.empty_archive_summary()
            summary.pop("green_partial_count")
            summary.update(
                total_count=2,
                total_energy_kwh=20,
                total_green_energy_kwh=3,
                has_green_energy=True,
            )
            summary["owners"] = {
                "entry:left": {key: value for key, value in summary.items() if key != "owners"}
            }
            history_store.write_archive_summary(path, summary)
            data = history_views.dashboard_session_data(path, source_instance_id="left")
            self.assertEqual(data["total_green_energy_kwh"], 3)
            self.assertTrue(data["total_green_partial"])
            other = history_views.dashboard_session_data(path, source_instance_id="right")
            self.assertIsNone(other["total_green_energy_kwh"])
            self.assertFalse(other["total_green_partial"])
