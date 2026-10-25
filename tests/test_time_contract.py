"""UTC presentation never changes retained session identities or guesses DST folds."""
import csv
from datetime import datetime
import importlib
from pathlib import Path
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).parents[1] / 'custom_components/growatt_thor'
package = types.ModuleType('thor_time_contract_test')
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
time = importlib.import_module(package.__name__ + '.runtime.time')
history = importlib.import_module(package.__name__ + '.sessions.csv')


class UtcTimeContractTest(unittest.TestCase):
    def test_offsets_and_unique_local_instants_normalize_to_utc(self):
        for raw, zone, expected in (
            ('2026-07-01 10:00:00', 'Europe/Berlin', '2026-07-01T08:00:00Z'),
            ('2026-01-01 10:00:00', 'Europe/Berlin', '2026-01-01T09:00:00Z'),
            ('2026-10-25T02:30:00+02:00', None, '2026-10-25T00:30:00Z'),
            ('2026-10-25T02:30:00+01:00', None, '2026-10-25T01:30:00Z'),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(time.utc_timestamp(raw, zone), expected)

    def test_missing_zone_fold_gap_and_invalid_dates_are_unknown(self):
        for raw, zone in (
            ('2026-10-25 02:30:00', 'Europe/Berlin'),
            ('2026-03-29 02:30:00', 'Europe/Berlin'),
            ('2026-07-01 10:00:00', None),
            ('2026-07-01 10:00:00', 'Invalid/Zone'),
            ('2026-02-30 10:00:00', 'Europe/Berlin'),
        ):
            with self.subTest(raw=raw, zone=zone):
                self.assertIsNone(time.utc_timestamp(raw, zone))

    def test_history_detail_and_export_agree_without_changing_csv_or_identity(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sessions.csv'
            export = Path(directory) / 'export.csv'
            with path.open('w', newline='', encoding='utf8') as stream:
                writer = csv.DictWriter(stream, fieldnames=history.SESSION_LOG_HEADERS)
                writer.writeheader()
                writer.writerow({'charger_id': 'THOR', 'transaction_id': '1',
                    'start_time': '2026-07-01 10:00:00', 'end_time': '2026-07-01 11:00:00',
                    'events': json.dumps([{'type': 'plugged_in', 'at': '2026-07-01 09:59:00', 'source': 'growatt', 'certainty': 'observed'}]),
                    'power_curve': json.dumps([['2026-07-01T10:00:00+02:00', 7000]])})
            original = path.read_bytes()
            row = history.dashboard_session_data(path, time_zone='Europe/Berlin')['items'][0]
            self.assertEqual(row['start_time'], '2026-07-01T08:00:00Z')
            self.assertEqual(row['events'][0]['at'], '2026-07-01T07:59:00Z')
            self.assertEqual(row['power_curve'][0][0], row['start_time'])
            detail = history.session_detail_data(path, row['session_id'], time_zone='Europe/Berlin')
            self.assertEqual(row, detail)
            other_zone = history.dashboard_session_data(path, time_zone='America/New_York')['items'][0]
            self.assertEqual(row['session_id'], other_zone['session_id'])
            history.export_session_rows(path, export, date_from=datetime(2026, 7, 1), date_to=datetime(2026, 7, 1, 23, 59, 59), time_zone='Europe/Berlin')
            with export.open(newline='', encoding='utf8') as stream:
                self.assertEqual(next(csv.DictReader(stream))['start_time'], row['start_time'])
            self.assertEqual(path.read_bytes(), original)

    def test_unresolvable_legacy_time_remains_in_csv_but_is_not_an_instant(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sessions.csv'
            with path.open('w', newline='', encoding='utf8') as stream:
                writer = csv.DictWriter(stream, fieldnames=history.SESSION_LOG_HEADERS)
                writer.writeheader()
                writer.writerow({'start_time': '2026-10-25 02:30:00', 'energy_kwh': 2})
            original = path.read_bytes()
            row = history.dashboard_session_data(path, time_zone='Europe/Berlin')['items'][0]
            self.assertIsNone(row['start_time'])
            self.assertEqual(row['energy_kwh'], 2)
            self.assertTrue(row['session_id'].startswith('legacy-'))
            self.assertEqual(path.read_bytes(), original)

    def test_last_session_time_sensors_expose_utc_without_rewriting_source_state(self):
        from test_multi_entry import _build_coordinator
        from test_energy_charged_sensor import sensor
        c = _build_coordinator()
        c.hass.config = types.SimpleNamespace(time_zone='Europe/Berlin')
        for cls, field in ((sensor.LastSessionStartSensor, 'start'), (sensor.LastSessionEndSensor, 'end'), (sensor.LastSessionPlugTimeSensor, 'plug_time'), (sensor.LastSessionUnplugTimeSensor, 'unplug_time')):
            with self.subTest(field=field):
                setattr(c, 'last_session_' + field, '2026-07-01 10:00:00')
                entity = object.__new__(cls)
                entity.coordinator = c
                self.assertEqual(entity.native_value, '2026-07-01T08:00:00Z')
                self.assertEqual(getattr(c, 'last_session_' + field), '2026-07-01 10:00:00')

    def test_new_session_duration_uses_elapsed_instants_across_spring_transition(self):
        from test_multi_entry import _build_coordinator
        from custom_components.growatt_thor.sessions.records import parse_growatt_session_record
        c = _build_coordinator()
        c.hass.config = types.SimpleNamespace(time_zone='Europe/Berlin')
        c.hass.async_create_task = lambda coro: coro.close()
        record = parse_growatt_session_record('currentrecord', 'transactionId=99&starttime=2026-03-29 01:30:00&endtime=2026-03-29 03:30:00&costenergy=1000&costmoney=100')
        c.sessions.process_session_record(record)
        self.assertEqual(c.last_session_duration_minutes, 60)
        self.assertEqual(c.last_session_start, '2026-03-29 01:30:00')
