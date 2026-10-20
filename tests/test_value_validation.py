"""Tests for strict service, entity, and config-entry input validation."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
    / "value_validation.py"
)
SPEC = importlib.util.spec_from_file_location(
    "growatt_thor_value_validation_test_target",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
validation = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validation
SPEC.loader.exec_module(validation)


class NumericValidationTest(unittest.TestCase):
    """Reject values that would otherwise be rounded into another intent."""

    def test_valid_decimal_is_returned_without_rounding(self):
        self.assertEqual(
            str(
                validation.validate_number(
                    4.2,
                    minimum=0.1,
                    maximum=200,
                    step=0.1,
                )
            ),
            "4.2",
        )

    def test_decimal_formatting_keeps_integer_zeroes(self):
        for value, expected in (("4.200", "4.2"), ("0", "0"), ("200", "200")):
            with self.subTest(value=value):
                self.assertEqual(
                    validation.format_decimal(validation.Decimal(value)),
                    expected,
                )

    def test_non_finite_numbers_are_always_rejected(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(
                    validation.NumericValidationError
                ) as raised:
                    validation.validate_number(
                        value,
                        minimum=-2,
                        maximum=2,
                        step=0.01,
                    )
                self.assertEqual(
                    raised.exception.reason,
                    validation.NumericValidationReason.NOT_FINITE,
                )

    def test_bounds_are_checked_before_payload_formatting(self):
        for value in (-2.01, 2.01):
            with self.subTest(value=value):
                with self.assertRaises(
                    validation.NumericValidationError
                ) as raised:
                    validation.validate_number(
                        value,
                        minimum=-2,
                        maximum=2,
                        step=0.01,
                    )
                self.assertEqual(
                    raised.exception.reason,
                    validation.NumericValidationReason.OUT_OF_RANGE,
                )

    def test_step_mismatch_is_rejected_instead_of_rounded(self):
        for value, step in ((6.6, 1), (4.25, 0.1), (0.011, 0.01)):
            with self.subTest(value=value, step=step):
                with self.assertRaises(
                    validation.NumericValidationError
                ) as raised:
                    validation.validate_number(
                        value,
                        minimum=0,
                        maximum=32,
                        step=step,
                    )
                self.assertEqual(
                    raised.exception.reason,
                    validation.NumericValidationReason.STEP_MISMATCH,
                )

    def test_boolean_is_not_accepted_as_number(self):
        with self.assertRaises(validation.NumericValidationError) as raised:
            validation.validate_number(
                True,
                minimum=0,
                maximum=1,
                step=1,
            )
        self.assertEqual(
            raised.exception.reason,
            validation.NumericValidationReason.INVALID,
        )

    def test_tcp_port_requires_an_exact_integer_in_protocol_range(self):
        self.assertEqual(validation.validate_tcp_port(9000), 9000)
        self.assertEqual(validation.validate_tcp_port("9000"), 9000)
        for value in (0, 65536, 9000.5, float("nan")):
            with self.subTest(value=value):
                with self.assertRaises(validation.NumericValidationError):
                    validation.validate_tcp_port(value)

    def test_poll_interval_requires_whole_finite_seconds(self):
        self.assertEqual(
            validation.validate_poll_interval("30", minimum=5),
            30,
        )
        for value in (4, 5.5, float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(validation.NumericValidationError):
                    validation.validate_poll_interval(value, minimum=5)


class ExportDateRangeValidationTest(unittest.TestCase):
    """Keep malformed and reversed date ranges out of the executor job."""

    def test_inclusive_range_expands_end_of_day(self):
        date_from, date_to = validation.parse_export_date_range(
            "2026-08-24",
            "2026-08-25",
        )

        self.assertEqual(date_from.isoformat(), "2026-08-24T00:00:00")
        self.assertEqual(date_to.isoformat(), "2026-08-25T23:59:59")

    def test_invalid_dates_have_stable_reason(self):
        for date_from, date_to in (
            ("not-a-date", "2026-08-25"),
            ("2026-02-30", "2026-08-25"),
            (None, "2026-08-25"),
        ):
            with self.subTest(date_from=date_from, date_to=date_to):
                with self.assertRaises(
                    validation.DateRangeValidationError
                ) as raised:
                    validation.parse_export_date_range(date_from, date_to)
                self.assertEqual(
                    raised.exception.reason,
                    validation.DateRangeValidationReason.INVALID_FORMAT,
                )

    def test_reversed_range_has_distinct_reason(self):
        with self.assertRaises(
            validation.DateRangeValidationError
        ) as raised:
            validation.parse_export_date_range(
                "2026-08-25",
                "2026-08-24",
            )

        self.assertEqual(
            raised.exception.reason,
            validation.DateRangeValidationReason.REVERSED_RANGE,
        )


if __name__ == "__main__":
    unittest.main()
