"""Characterize legacy parsing differences before sharing conversion helpers."""

from __future__ import annotations

import importlib
import math
import sys
import types
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

PACKAGE_NAME = "thor_parser_contract_test"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(Path(__file__).parents[1] / "custom_components/growatt_thor")]
sys.modules[PACKAGE_NAME] = package


def load(name):
    return importlib.import_module(f"{PACKAGE_NAME}.{name}")


time = load("timestamps")
observations = load("energy.site_observations")
duration = load("sessions.duration")
series = load("sessions.series")
state = load("sessions.state")
correlation = load("sessions.correlation")
records = load("sessions.records")
active = load("sessions.active_state")
meter = load("energy.meter_observations")
identity = load("sessions.identity")
faults = load("charging.faults")
schedule = load("targets.schedule")


class ParserContractTest(unittest.TestCase):
    def test_utc_boundary_requires_an_explicit_or_unambiguous_zone(self):
        self.assertIsNone(time.utc_instant("2026-10-27T10:00:00"))
        self.assertIsNone(time.utc_instant("2026-10-25T02:30:00", "Europe/Berlin"))
        self.assertIsNone(time.utc_instant("2026-03-29T02:30:00", "Europe/Berlin"))
        self.assertIsNone(time.utc_instant("2026-10-27"))
        self.assertIsNone(time.utc_instant(datetime(2026, 10, 27, tzinfo=UTC)))
        self.assertEqual(
            time.utc_instant(" 2026-10-27T10:00:00+02:00 "),
            datetime(2026, 10, 27, 8, tzinfo=UTC),
        )

    def test_site_observations_accept_datetimes_but_reject_naive_times_and_spaces(self):
        aware = datetime(2026, 10, 27, 10, tzinfo=UTC)
        self.assertEqual(observations.parse_at(aware), aware)
        for value in (
            None,
            "",
            "not-a-time",
            "2026-10-27",
            "2026-10-27T10:00:00",
            " 2026-10-27T10:00:00Z ",
        ):
            with self.subTest(value=value):
                self.assertIsNone(observations.parse_at(value))
        self.assertEqual(observations.parse_at("2026-10-27T10:00:00Z"), aware)

    def test_effective_duration_preserves_naive_times_and_original_offsets(self):
        self.assertEqual(duration._timestamp("2026-10-27"), datetime(2026, 10, 27))
        self.assertEqual(duration._timestamp("2026-10-27T10:00:00").tzinfo, None)
        parsed = duration._timestamp("2026-10-27T10:00:00+02:00")
        self.assertEqual(parsed.hour, 10)
        self.assertEqual(parsed.utcoffset(), timedelta(hours=2))
        self.assertIsNone(duration._timestamp(" 2026-10-27T10:00:00Z "))

    def test_series_strips_spaces_and_accepts_naive_calendar_dates(self):
        self.assertEqual(
            series._timestamp(" 2026-10-27T10:00:00Z "),
            datetime(2026, 10, 27, 10, tzinfo=UTC).timestamp(),
        )
        self.assertEqual(series._timestamp("2026-10-27"), datetime(2026, 10, 27).timestamp())
        for value in (None, 12, "", "bad"):
            self.assertIsNone(series._timestamp(value))

    def test_loose_numbers_keep_nonfinite_and_negative_values(self):
        for parser in (state._optional_float, correlation._optional_float, records._optional_float):
            with self.subTest(parser=parser):
                self.assertEqual(parser("-1"), -1)
                self.assertEqual(parser("inf"), math.inf)
                self.assertTrue(math.isnan(parser("NaN")))
                self.assertIsNone(parser(""))
                self.assertIsNone(parser("bad"))
        with self.assertRaises(TypeError):
            records._optional_float([])

    def test_nonnegative_numbers_keep_their_distinct_input_types(self):
        self.assertEqual(active._number(Decimal("12")), 12)
        self.assertIsNone(meter._number(Decimal("12")))
        for parser in (active._number, meter._number):
            for value in (None, "", "bad", "NaN", "inf", "-1"):
                with self.subTest(parser=parser, value=value):
                    self.assertIsNone(parser(value))
            self.assertEqual(parser(True), 1)
            self.assertEqual(parser("0"), 0)

    def test_optional_text_preserves_whitespace_and_length_contracts(self):
        for parser in (
            state._optional_text,
            correlation._optional_text,
            active._text,
            faults._text,
        ):
            self.assertIsNone(parser(None))
            self.assertIsNone(parser(""))
            self.assertEqual(parser("  "), "  ")
            self.assertEqual(parser(False), "False")
        self.assertEqual(active._text("x" * 300), "x" * 256)
        self.assertEqual(state._optional_text("x" * 300), "x" * 300)
        self.assertEqual(identity._text(None), "")
        self.assertEqual(identity._text(""), "")

    def test_schedule_retained_times_strip_spaces_and_require_offsets(self):
        self.assertEqual(
            schedule.stored_start_at(" 2026-10-27T10:00:00+02:00 "),
            datetime(2026, 10, 27, 8, tzinfo=UTC),
        )
        for value in (None, datetime.now(UTC), "2026-10-27", "2026-10-27T10:00:00", "bad"):
            self.assertIsNone(schedule.stored_start_at(value))
