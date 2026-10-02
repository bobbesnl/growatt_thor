"""Pure validation tests for persisted one-shot target schedules."""

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path

MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
    / "targets/schedule.py"
)
SPEC = importlib.util.spec_from_file_location("charging_target_schedule_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
schedule = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(schedule)


class ChargingTargetScheduleTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)

    def test_timezone_aware_value_is_normalized_to_utc(self):
        parsed = schedule.parse_start_at("2026-09-11T12:05:00+02:00", now=self.now)
        self.assertEqual(schedule.iso_utc(parsed), "2026-09-11T10:05:00Z")

    def test_start_must_be_future_timezone_aware_and_within_thirty_days(self):
        for value, message in (
            (None, "iso_datetime"),
            ("not-a-time", "iso_datetime"),
            ("2026-09-11T10:05:00", "timezone_required"),
            ("2026-09-11T10:00:00Z", "must_be_future"),
            ("2026-10-12T10:00:00Z", "too_far"),
        ):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, message):
                schedule.parse_start_at(value, now=self.now)

    def test_retained_parser_accepts_past_values_without_reclassifying_them(self):
        self.assertEqual(
            schedule.stored_start_at("2026-09-10T10:00:00Z"),
            datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc),
        )
        self.assertIsNone(schedule.stored_start_at("2026-09-10T10:00:00"))
        self.assertIsNone(schedule.stored_start_at("invalid"))

    def test_reservation_expiry_uses_home_assistant_local_wall_clock(self):
        start = datetime(2026, 9, 11, 10, 5, tzinfo=timezone.utc)
        self.assertEqual(
            schedule.reservation_expiry(start, "Europe/Berlin"),
            "2026-09-11T12:05:00.000",
        )
        with self.assertRaisesRegex(ValueError, "invalid_time_zone"):
            schedule.reservation_expiry(start, "Mars/Olympus")

    def test_daily_recurrence_preserves_local_clock_across_dst(self):
        previous = datetime(2026, 10, 24, 18, 30, tzinfo=timezone.utc)  # 20:30 CEST
        now = datetime(2026, 10, 25, 20, 0, tzinfo=timezone.utc)
        next_run = schedule.next_daily_start(
            previous, now=now, time_zone="Europe/Berlin"
        )
        self.assertEqual(next_run, datetime(2026, 10, 26, 19, 30, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
