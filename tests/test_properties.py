"""Property-based tests for site accounting and the value and time parsers.

Hypothesis generates inputs, including edge values such as NaN, infinities,
negative power and daylight-saving transitions, and checks rules that must hold
for every input rather than for a few chosen examples.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from tests.support import load_package_module, register_package

NAME = "thor_property_test_package"
register_package(NAME)
load_package_module("energy.sources", package_name=NAME)
allocation = load_package_module("energy.allocation", package_name=NAME)
site_observations = load_package_module("energy.site_observations", package_name=NAME)
coerce = load_package_module("coerce", package_name=NAME)
timestamps = load_package_module("timestamps", package_name=NAME)
validation = load_package_module("configuration.validation", package_name=NAME)

AT = datetime(2026, 9, 22, 12, tzinfo=UTC)
TOLERANCE = 1e-9
PROPERTY_SETTINGS = settings(deadline=None, max_examples=200)


@st.composite
def observations(draw: st.DrawFn) -> object | None:
    """Mostly fresh readings, plus stale, missing and non-finite ones."""
    kind = draw(st.sampled_from(["fresh", "fresh", "fresh", "stale", "missing", "invalid"]))
    if kind == "missing":
        return draw(st.sampled_from([None, site_observations.PowerObservation(None, AT)]))
    if kind == "invalid":
        value = draw(st.sampled_from([float("nan"), float("inf"), float("-inf")]))
        return site_observations.PowerObservation(value, AT)
    value = draw(st.floats(min_value=-10_000, max_value=50_000, allow_nan=False))
    age = (
        draw(st.integers(min_value=0, max_value=120))
        if kind == "fresh"
        else draw(st.one_of(st.integers(-30, -1), st.integers(121, 600)))
    )
    return site_observations.PowerObservation(value, AT - timedelta(seconds=age))


@st.composite
def sites(draw: st.DrawFn) -> object:
    return site_observations.SiteObservations(
        grid=draw(observations()),
        solar=draw(observations()),
        household=draw(observations()),
        battery=draw(observations()),
        direct_grid=draw(st.one_of(st.none(), observations())),
        direct_solar=draw(st.one_of(st.none(), observations())),
    )


policies = st.builds(
    allocation.AccountingPolicy,
    policy_id=st.sampled_from(["grid_first", "load_first"]),
    topology=st.sampled_from(["grid_only", "pv", "pv_battery"]),
)
prices = st.one_of(
    st.none(), st.floats(min_value=0, max_value=2, allow_nan=False), st.just(float("nan"))
)


class AllocationPropertyTest(unittest.TestCase):
    @PROPERTY_SETTINGS
    @given(
        kwh=st.floats(min_value=0.0001, max_value=80, allow_nan=False),
        minutes=st.integers(min_value=1, max_value=24 * 60),
        site=sites(),
        policy=policies,
        price=prices,
    )
    def test_allocation_books_every_kwh_exactly_once(self, kwh, minutes, site, policy, price):
        delta = allocation.EVEnergyDelta(
            "site", "charger", "tx", AT - timedelta(minutes=minutes), AT, kwh
        )
        result = allocation.allocate(delta, site, allocation.Tariff(price), policy)

        parts = (result.direct_solar, result.direct_grid, result.battery_unknown, result.unknown)
        self.assertTrue(all(part >= 0 for part in parts), parts)
        self.assertAlmostEqual(sum(parts), kwh, delta=TOLERANCE * max(1.0, kwh))
        self.assertGreaterEqual(result.data_quality.coverage, 0)
        self.assertLessEqual(result.data_quality.coverage, 1)
        if policy.topology == "grid_only" and site.direct_solar is None:
            self.assertEqual(result.direct_solar, 0)
        if policy.topology != "pv_battery":
            self.assertEqual(result.battery_unknown, 0)
        if price is None or price != price:
            self.assertIsNone(result.effective_grid_cost)
        else:
            self.assertAlmostEqual(result.effective_grid_cost, result.direct_grid * price)

    @PROPERTY_SETTINGS
    @given(kwh=st.one_of(st.floats(max_value=-1e-9), st.just(float("nan"))), site=sites())
    def test_allocation_rejects_negative_or_unknown_energy(self, kwh, site):
        delta = allocation.EVEnergyDelta("site", "charger", "tx", AT - timedelta(hours=1), AT, kwh)
        with self.assertRaises(ValueError):
            allocation.allocate(delta, site, allocation.Tariff(None), allocation.AccountingPolicy())


class ValueParserPropertyTest(unittest.TestCase):
    @PROPERTY_SETTINGS
    @given(
        st.one_of(
            st.none(),
            st.booleans(),
            st.integers(),
            st.floats(),
            st.text(max_size=20),
            st.binary(max_size=8),
            st.lists(st.integers(), max_size=2),
        )
    )
    def test_optional_float_returns_a_finite_number_or_none(self, value):
        number = coerce.optional_float(value)
        if number is not None:
            self.assertIsInstance(number, float)
            self.assertEqual(number, number)
            self.assertNotIn(number, (float("inf"), float("-inf")))

    @PROPERTY_SETTINGS
    @given(st.floats(allow_nan=False, allow_infinity=False))
    def test_optional_float_keeps_finite_numbers_and_their_text(self, value):
        self.assertEqual(coerce.optional_float(value), value)
        self.assertEqual(coerce.optional_float(repr(value)), value)

    @PROPERTY_SETTINGS
    @given(
        minimum=st.integers(min_value=-100, max_value=100),
        span=st.integers(min_value=0, max_value=1000),
        step=st.sampled_from(["1", "0.5", "0.1", "0.01", "5"]),
        value=st.one_of(
            st.integers(min_value=-1000, max_value=2000),
            st.decimals(min_value=-1000, max_value=2000, places=3),
            st.floats(min_value=-1000, max_value=2000, allow_nan=False),
        ),
    )
    def test_validate_number_accepts_exact_matches_and_never_rounds(
        self, minimum, span, step, value
    ):
        maximum = minimum + span
        step_decimal = Decimal(step)
        exact = Decimal(str(value))
        expected = minimum <= exact <= maximum and (exact - minimum) % step_decimal == 0
        try:
            result = validation.validate_number(
                value, minimum=minimum, maximum=maximum, step=step_decimal
            )
        except validation.NumericValidationError:
            self.assertFalse(expected, value)
        else:
            self.assertTrue(expected, value)
            self.assertEqual(result, exact)
            self.assertEqual(Decimal(validation.format_decimal(result)), result)

    @PROPERTY_SETTINGS
    @given(st.one_of(st.integers(min_value=-10, max_value=70_000), st.floats(), st.booleans()))
    def test_tcp_ports_are_whole_numbers_in_range(self, value):
        try:
            port = validation.validate_tcp_port(value)
        except validation.NumericValidationError:
            self.assertFalse(
                not isinstance(value, bool)
                and value == value
                and value not in (float("inf"), float("-inf"))
                and float(value).is_integer()
                and 1 <= value <= 65535
            )
        else:
            self.assertNotIsInstance(value, bool)
            self.assertEqual(port, value)
            self.assertTrue(1 <= port <= 65535)

    @PROPERTY_SETTINGS
    @given(
        minimum=st.integers(min_value=1, max_value=60),
        value=st.one_of(st.integers(min_value=-10, max_value=100_000), st.floats()),
    )
    def test_poll_intervals_are_whole_seconds_at_or_above_the_minimum(self, minimum, value):
        try:
            interval = validation.validate_poll_interval(value, minimum=minimum)
        except validation.NumericValidationError:
            self.assertFalse(
                value == value
                and value not in (float("inf"), float("-inf"))
                and float(value).is_integer()
                and value >= minimum
            )
        else:
            # Like every numeric validator, the decimal text is authoritative,
            # not the binary float residue (matters above 2**53).
            self.assertEqual(interval, Decimal(str(value)))
            self.assertGreaterEqual(interval, minimum)


aware_datetimes = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2100, 1, 1),
    timezones=st.sampled_from(
        [UTC, ZoneInfo("Europe/Berlin"), ZoneInfo("America/New_York"), ZoneInfo("Asia/Kolkata")]
    ),
    # Wall times inside a daylight-saving gap do not exist and have no instant.
    allow_imaginary=False,
)


class TimeParserPropertyTest(unittest.TestCase):
    @PROPERTY_SETTINGS
    @given(aware_datetimes)
    def test_aware_iso_text_round_trips_to_the_same_utc_instant(self, moment):
        # Compare POSIX timestamps: PEP 495 makes repeated wall times compare
        # unequal across zones even when they denote the same instant.
        parsed = timestamps.parse_utc(moment.isoformat())
        self.assertEqual(parsed.timestamp(), moment.timestamp())
        self.assertIs(parsed.tzinfo, UTC)

        text = timestamps.utc_timestamp(moment.isoformat())
        self.assertTrue(text.endswith("Z"))
        self.assertEqual(timestamps.parse_utc(text).timestamp(), moment.timestamp())

    @PROPERTY_SETTINGS
    @given(st.text(max_size=40))
    def test_parsers_return_none_instead_of_raising_on_arbitrary_text(self, text):
        for parsed in (
            timestamps.parse_utc(text),
            timestamps.utc_instant(text, "Europe/Berlin"),
        ):
            self.assertTrue(parsed is None or parsed.tzinfo is not None)

    @PROPERTY_SETTINGS
    @given(
        st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2100, 1, 1)),
        st.sampled_from(["Europe/Berlin", "America/New_York", "Australia/Sydney"]),
    )
    def test_local_wall_time_resolves_only_when_unambiguous(self, wall_time, zone_name):
        wall_time = wall_time.replace(microsecond=0)
        resolved = timestamps.utc_instant(wall_time.isoformat(), zone_name)
        zone = ZoneInfo(zone_name)
        candidates = {
            wall_time.replace(tzinfo=zone, fold=fold).astimezone(UTC)
            for fold in (0, 1)
            if wall_time.replace(tzinfo=zone, fold=fold)
            .astimezone(UTC)
            .astimezone(zone)
            .replace(tzinfo=None)
            == wall_time
        }
        assume(wall_time.year < 2100)
        if len(candidates) == 1:
            self.assertEqual(resolved, candidates.pop())
            self.assertEqual(resolved.astimezone(zone).replace(tzinfo=None), wall_time)
        else:
            # Daylight-saving gaps and repeated hours are not guessed.
            self.assertIsNone(resolved)


if __name__ == "__main__":
    unittest.main()
