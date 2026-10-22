"""Tests for the bounded session-card CSV projection."""
import csv
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

COMPONENT = Path(__file__).parents[1] / "custom_components/growatt_thor"
PACKAGE_NAME = "thor_session_dashboard_test"
PACKAGE = types.ModuleType(PACKAGE_NAME)
PACKAGE.__path__ = [str(COMPONENT)]
sys.modules[PACKAGE_NAME] = PACKAGE

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, COMPONENT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

load(f"{PACKAGE_NAME}.sessions.identity", "sessions/identity.py")
session_csv = load(f"{PACKAGE_NAME}.sessions.csv", "sessions/csv.py")


class SessionDashboardTest(unittest.TestCase):
    def test_missing_log_has_known_zero_totals_and_unknown_green_energy(self):
        with tempfile.TemporaryDirectory() as directory:
            data = session_csv.dashboard_session_data(Path(directory) / "missing.csv")
        self.assertEqual(data["items"], [])
        self.assertEqual(data["total_energy_kwh"], 0.0)
        self.assertIsNone(data["total_green_energy_kwh"])

    def test_history_is_bounded_sorted_and_keeps_identifier(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.csv"
            with path.open("w", newline="", encoding="utf-8") as target:
                writer = csv.DictWriter(target, fieldnames=session_csv.SESSION_LOG_HEADERS)
                writer.writeheader()
                writer.writerow({"start_time": "2026-09-10 10:00:00", "energy_kwh": "2.5", "cost": "0.70", "authorized_identifier": "RFID-A"})
                writer.writerow({"start_time": "2026-09-11 10:00:00", "energy_kwh": "3.5", "cost": "1.10", "authorized_identifier": "freevenID", "power_curve": '[["2026-09-11T10:00:00Z",7200],["bad",-1]]'})
            data = session_csv.dashboard_session_data(path, limit=1)
        self.assertEqual(data["total_count"], 2)
        self.assertEqual(data["total_energy_kwh"], 6.0)
        self.assertEqual(data["items"][0]["authorized_identifier"], "freevenID")
        self.assertFalse(data["items"][0]["active"])
        self.assertIsNone(data["items"][0]["green_energy_kwh"])
        self.assertEqual(data["items"][0]["power_curve"], [["2026-09-11T10:00:00Z", 7200.0]])



class MultiChargerHistoryTest(unittest.TestCase):
    def test_history_totals_and_details_are_scoped_before_limiting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sessions.csv'
            for name, energy in [('left', 2), ('right', 7)]:
                session_csv.append_session_row(path, {
                    'source_instance_id': name, 'charger_id': 'THOR-' + name,
                    'session_id': name, 'session_source': 'home_assistant',
                    'start_time': '2026-10-21T10:00:00Z', 'energy_kwh': energy,
                })
            left = session_csv.dashboard_session_data(path, source_instance_id='left', limit=1)
            self.assertEqual(left['total_energy_kwh'], 2)
            self.assertEqual([item['session_id'] for item in left['items']], ['left'])
            self.assertIsNone(session_csv.session_detail_data(path, 'right', source_instance_id='left'))
            self.assertEqual(session_csv.session_detail_data(path, 'right', source_instance_id='right')['energy_kwh'], 7)
            self.assertEqual(session_csv.dashboard_session_data(path)['total_energy_kwh'], 9)

    def test_legacy_rows_require_matching_charger_and_explicit_owner_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sessions.csv'
            for name, owner, energy in [('legacy', '', 2), ('owned', 'right', 7)]:
                session_csv.append_session_row(path, {
                    'source_instance_id': owner, 'charger_id': 'THOR',
                    'session_id': name, 'session_source': 'home_assistant',
                    'start_time': '2026-10-21T10:00:00Z', 'energy_kwh': energy,
                })
            self.assertEqual(session_csv.dashboard_session_data(path, source_instance_id='left')['total_count'], 0)
            self.assertEqual(session_csv.dashboard_session_data(path, source_instance_id='left', charge_point_id='THOR')['total_energy_kwh'], 2)

    def test_retention_preserves_separate_totals(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sessions.csv'
            for name, energy in [('left', 2), ('right', 7)]:
                session_csv.append_session_row(path, {
                    'source_instance_id': name, 'charger_id': 'THOR-' + name,
                    'session_id': name, 'session_source': 'home_assistant',
                    'start_time': '2020-01-01T10:00:00Z', 'energy_kwh': energy,
                })
            session_csv.enforce_session_retention(path)
            for name, energy in [('left', 2), ('right', 7)]:
                data = session_csv.dashboard_session_data(path, source_instance_id=name)
                self.assertEqual(data['items'], [])
                self.assertEqual(data['total_energy_kwh'], energy)
                self.assertEqual(data['total_count'], 1)

    def test_unlabelled_archive_is_inherited_only_by_the_original_single_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sessions.csv'
            archive = session_csv._empty_archive_summary()
            archive.update(total_energy_kwh=12.5, total_count=3)
            session_csv._write_archive_summary(path, archive)
            inherited = session_csv.dashboard_session_data(path, source_instance_id='original', include_unassigned_archive=True)
            other = session_csv.dashboard_session_data(path, source_instance_id='new')
            self.assertEqual(inherited['total_energy_kwh'], 12.5)
            self.assertEqual(inherited['total_count'], 3)
            self.assertEqual(other['total_count'], 0)


if __name__ == "__main__":
    unittest.main()
