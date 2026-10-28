"""UTC presentation never changes retained session identities or guesses DST folds."""

import csv
import importlib
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parents[1] / "custom_components/growatt_thor"
package = types.ModuleType("thor_time_contract_test")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
time = importlib.import_module(package.__name__ + ".timestamps")
history = importlib.import_module(package.__name__ + ".sessions.csv")


class UtcTimeContractTest(unittest.TestCase):
    def test_completed_fixed_clock_session_retains_identity_and_roundtrips_as_utc(self):
        import json

        from test_multi_entry import _build_coordinator

        from custom_components.growatt_thor.configuration.values import (
            configuration_value_from_item,
        )
        from custom_components.growatt_thor.presentation.card_data import (
            dashboard_active_session,
        )
        from custom_components.growatt_thor.sessions.records import (
            parse_growatt_session_record,
        )

        c = _build_coordinator()
        c.hass.config = types.SimpleNamespace(time_zone="Europe/Berlin")
        c.hass.async_create_task = lambda coro: coro.close()
        c._schedule_storage_save = lambda: None
        c.now = lambda: "2026-10-27T11:01:25Z"
        c.configuration_values = {
            key: configuration_value_from_item({"key": key, "value": value})
            for key, value in {
                "G_TimeZone": "UTC+2",
                "G_DaylightSavingTime": "00-00&00-00",
            }.items()
        }
        c.start_transaction(51, connector_id=1, meter_start=0, timestamp="2026-10-27T13:01:23")
        active = dashboard_active_session(c)
        c._active_power_curve = [
            ["2026-10-27T11:01:23Z", 7300],
            ["2026-10-27T13:54:08Z", 7350],
        ]
        c._session_event_tracker.observe_power("2026-10-27T11:01:23Z", 7300)
        c.now = lambda: "2026-10-27T13:54:13Z"
        c.record_status_notification(1, "SuspendedEV", "NoError")
        c.now = lambda: "2026-10-27T14:07:38Z"
        c.stop_transaction(
            transaction_id=51,
            reason="Remote",
            meter_stop=20252,
            timestamp="2026-10-27T16:07:37",
        )
        c.runtime_data["append_session_to_csv"] = object()
        record = parse_growatt_session_record(
            "currentrecord",
            "transactionId=51&plugtime=2026-10-27 13:01:17&starttime=2026-10-27 13:01:23&"
            "endtime=2026-10-27 16:07:37&unplugtime=2026-10-27 16:07:37&costenergy=20252&"
            "costmoney=465",
        )
        c.sessions.process_session_record(record)
        (row,) = c.sessions.outbox.snapshot()
        self.assertEqual(row["session_id"], active["session_id"])
        self.assertEqual(row["start_time"], active["start_time"])
        self.assertEqual(row["start_time"], "2026-10-27T11:01:23Z")
        self.assertEqual(row["end_time"], "2026-10-27T14:07:37Z")
        self.assertEqual(c.last_session_start, record.start_time)
        self.assertEqual(c.last_session_end, record.end_time)
        self.assertEqual(row["energy_kwh"], 20.252)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.csv"
            history.append_session_row(path, row)
            detail = history.session_detail_data(path, row["session_id"], time_zone="Europe/Berlin")
            self.assertEqual(detail["power_curve"], json.loads(row["power_curve"]))
            self.assertEqual(detail["start_time"], active["start_time"])
            self.assertEqual(
                next(e["at"] for e in detail["events"] if e["type"] == "charging_paused"),
                "2026-10-27T13:54:13Z",
            )
            self.assertNotIn("unplugged", {e["type"] for e in detail["events"]})
            # A later configuration change cannot reinterpret newly stored instants.
            self.assertEqual(
                history.session_detail_data(path, row["session_id"], time_zone="America/New_York"),
                detail,
            )

    def test_vendor_only_session_anchors_use_the_explicit_device_clock(self):
        from datetime import timedelta, timezone

        from test_session_events import session_events

        events = session_events.merge_growatt_record_events(
            [],
            plug_time="2026-10-27 13:01:17",
            start_time="2026-10-27 13:01:23",
            end_time="2026-10-27 16:07:37",
            unplug_time="2026-10-27 16:07:37",
            time_zone=timezone(timedelta(hours=2)),
        )
        self.assertEqual(
            [e["at"] for e in events],
            ["2026-10-27T11:01:17Z", "2026-10-27T11:01:23Z", "2026-10-27T14:07:37Z"],
        )

    def test_offsets_and_unique_local_instants_normalize_to_utc(self):
        for raw, zone, expected in (
            ("2026-07-01 10:00:00", "Europe/Berlin", "2026-07-01T08:00:00Z"),
            ("2026-01-01 10:00:00", "Europe/Berlin", "2026-01-01T09:00:00Z"),
            ("2026-10-25T02:30:00+02:00", None, "2026-10-25T00:30:00Z"),
            ("2026-10-25T02:30:00+01:00", None, "2026-10-25T01:30:00Z"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(time.utc_timestamp(raw, zone), expected)

    def test_missing_zone_fold_gap_and_invalid_dates_are_unknown(self):
        for raw, zone in (
            ("2026-10-25 02:30:00", "Europe/Berlin"),
            ("2026-03-29 02:30:00", "Europe/Berlin"),
            ("2026-07-01 10:00:00", None),
            ("2026-07-01 10:00:00", "Invalid/Zone"),
            ("2026-02-30 10:00:00", "Europe/Berlin"),
        ):
            with self.subTest(raw=raw, zone=zone):
                self.assertIsNone(time.utc_timestamp(raw, zone))

    def test_history_detail_and_export_agree_without_changing_csv_or_identity(self):
        import json

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.csv"
            export = Path(directory) / "export.csv"
            with path.open("w", newline="", encoding="utf8") as stream:
                writer = csv.DictWriter(stream, fieldnames=history.SESSION_LOG_HEADERS)
                writer.writeheader()
                writer.writerow(
                    {
                        "charger_id": "THOR",
                        "transaction_id": "1",
                        "start_time": "2026-07-01 10:00:00",
                        "end_time": "2026-07-01 11:00:00",
                        "events": json.dumps(
                            [
                                {
                                    "type": "plugged_in",
                                    "at": "2026-07-01 09:59:00",
                                    "source": "growatt",
                                    "certainty": "observed",
                                }
                            ]
                        ),
                        "power_curve": json.dumps([["2026-07-01T10:00:00+02:00", 7000]]),
                    }
                )
            original = path.read_bytes()
            row = history.dashboard_session_data(path, time_zone="Europe/Berlin")["items"][0]
            self.assertEqual(row["start_time"], "2026-07-01T08:00:00Z")
            self.assertEqual(row["events"][0]["at"], "2026-07-01T07:59:00Z")
            self.assertEqual(row["power_curve"][0][0], row["start_time"])
            detail = history.session_detail_data(path, row["session_id"], time_zone="Europe/Berlin")
            self.assertEqual(row, detail)
            other_zone = history.dashboard_session_data(path, time_zone="America/New_York")[
                "items"
            ][0]
            self.assertEqual(row["session_id"], other_zone["session_id"])
            history.export_session_rows(
                path,
                export,
                date_from=datetime(2026, 7, 1),
                date_to=datetime(2026, 7, 1, 23, 59, 59),
                time_zone="Europe/Berlin",
            )
            with export.open(newline="", encoding="utf8") as stream:
                self.assertEqual(next(csv.DictReader(stream))["start_time"], row["start_time"])
            self.assertEqual(path.read_bytes(), original)

    def test_unresolvable_legacy_time_remains_in_csv_but_is_not_an_instant(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.csv"
            with path.open("w", newline="", encoding="utf8") as stream:
                writer = csv.DictWriter(stream, fieldnames=history.SESSION_LOG_HEADERS)
                writer.writeheader()
                writer.writerow({"start_time": "2026-10-25 02:30:00", "energy_kwh": 2})
            original = path.read_bytes()
            row = history.dashboard_session_data(path, time_zone="Europe/Berlin")["items"][0]
            self.assertIsNone(row["start_time"])
            self.assertEqual(row["energy_kwh"], 2)
            self.assertTrue(row["session_id"].startswith("legacy-"))
            self.assertEqual(path.read_bytes(), original)

    def test_last_session_time_sensors_expose_utc_without_rewriting_source_state(self):
        from test_energy_charged_sensor import sensor
        from test_multi_entry import _build_coordinator

        c = _build_coordinator()
        c.hass.config = types.SimpleNamespace(time_zone="Europe/Berlin")
        for cls, field in (
            (sensor.LastSessionStartSensor, "start"),
            (sensor.LastSessionEndSensor, "end"),
            (sensor.LastSessionPlugTimeSensor, "plug_time"),
            (sensor.LastSessionUnplugTimeSensor, "unplug_time"),
        ):
            with self.subTest(field=field):
                setattr(c, "last_session_" + field, "2026-07-01 10:00:00")
                entity = object.__new__(cls)
                entity.coordinator = c
                self.assertEqual(entity.native_value, "2026-07-01T08:00:00Z")
                self.assertEqual(getattr(c, "last_session_" + field), "2026-07-01 10:00:00")

    def test_new_session_duration_uses_elapsed_instants_across_spring_transition(self):
        from test_multi_entry import _build_coordinator

        from custom_components.growatt_thor.sessions.records import (
            parse_growatt_session_record,
        )

        c = _build_coordinator()
        c.hass.config = types.SimpleNamespace(time_zone="Europe/Berlin")
        c.hass.async_create_task = lambda coro: coro.close()
        record = parse_growatt_session_record(
            "currentrecord",
            "transactionId=99&starttime=2026-03-29 01:30:00&endtime=2026-03-29 03:30:00&"
            "costenergy=1000&costmoney=100",
        )
        c.sessions.process_session_record(record)
        self.assertEqual(c.last_session_duration_minutes, 60)
        self.assertEqual(c.last_session_start, "2026-03-29 01:30:00")
