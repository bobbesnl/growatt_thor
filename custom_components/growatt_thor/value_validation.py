"""Strict validation for numeric, network, and date-range inputs."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum


class NumericValidationReason(str, Enum):
    """Stable reason codes suitable for translated Home Assistant errors."""

    INVALID = "invalid"
    NOT_FINITE = "not_finite"
    OUT_OF_RANGE = "out_of_range"
    STEP_MISMATCH = "step_mismatch"


class NumericValidationError(ValueError):
    """Describe why a numeric value cannot be used without coercion."""

    def __init__(
        self,
        reason: NumericValidationReason,
        value: object,
        minimum: object | None = None,
        maximum: object | None = None,
        step: object | None = None,
    ) -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.value = value
        self.minimum = minimum
        self.maximum = maximum
        self.step = step


class DateRangeValidationReason(str, Enum):
    """Stable date-range failure reasons for service error mapping."""

    INVALID_FORMAT = "invalid_format"
    REVERSED_RANGE = "reversed_range"


class DateRangeValidationError(ValueError):
    """Reject malformed or reversed export date ranges."""

    def __init__(self, reason: DateRangeValidationReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


def validate_number(
    value: object,
    *,
    minimum: int | float | Decimal,
    maximum: int | float | Decimal,
    step: int | float | Decimal,
) -> Decimal:
    """Return an exact decimal only when bounds and step already match.

    ``Decimal(str(value))`` intentionally evaluates the human-facing decimal
    representation rather than binary floating-point residue.  The function
    never rounds: an automation requesting 6.6 A for a 1 A control receives an
    error instead of silently writing 7 A.
    """
    if isinstance(value, bool):
        raise NumericValidationError(NumericValidationReason.INVALID, value)
    try:
        numeric = Decimal(str(value))
        minimum_decimal = Decimal(str(minimum))
        maximum_decimal = Decimal(str(maximum))
        step_decimal = Decimal(str(step))
    except (InvalidOperation, TypeError, ValueError):
        raise NumericValidationError(
            NumericValidationReason.INVALID,
            value,
        ) from None

    if not numeric.is_finite():
        raise NumericValidationError(
            NumericValidationReason.NOT_FINITE,
            value,
        )
    if not minimum_decimal <= numeric <= maximum_decimal:
        raise NumericValidationError(
            NumericValidationReason.OUT_OF_RANGE,
            value,
            minimum=minimum,
            maximum=maximum,
        )
    if step_decimal <= 0:
        raise ValueError("Numeric validation step must be greater than zero")
    if (numeric - minimum_decimal) % step_decimal != 0:
        raise NumericValidationError(
            NumericValidationReason.STEP_MISMATCH,
            value,
            minimum=minimum,
            maximum=maximum,
            step=step,
        )
    return numeric


def format_decimal(value: Decimal) -> str:
    """Format an already validated decimal without exponent or lost zeros."""
    rendered = format(value, "f")
    # Only fractional zeroes may be removed.  Stripping ``"200"`` directly
    # would turn a valid 200 kWh request into the very different value 2.
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def validate_integer_range(
    value: object,
    *,
    minimum: int,
    maximum: int,
) -> int:
    """Validate an integer range without truncating float input."""
    return int(
        validate_number(
            value,
            minimum=minimum,
            maximum=maximum,
            step=1,
        )
    )


def validate_tcp_port(value: object) -> int:
    """Return one valid non-privileged-or-privileged TCP port number."""
    return validate_integer_range(value, minimum=1, maximum=65535)


def validate_poll_interval(value: object, *, minimum: int) -> int:
    """Return a whole-second polling interval at or above the safe minimum."""
    # Poll intervals deliberately have no arbitrary upper bound, so validate
    # finiteness, whole seconds, and the lower safety limit directly.
    if isinstance(value, bool):
        raise NumericValidationError(NumericValidationReason.INVALID, value)
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise NumericValidationError(
            NumericValidationReason.INVALID,
            value,
        ) from None
    if not numeric.is_finite():
        raise NumericValidationError(
            NumericValidationReason.NOT_FINITE,
            value,
        )
    if numeric < minimum:
        raise NumericValidationError(
            NumericValidationReason.OUT_OF_RANGE,
            value,
            minimum=minimum,
        )
    if numeric % 1 != 0:
        raise NumericValidationError(
            NumericValidationReason.STEP_MISMATCH,
            value,
            minimum=minimum,
            step=1,
        )
    return int(numeric)


def parse_export_date_range(
    date_from_value: object,
    date_to_value: object,
) -> tuple[datetime, datetime]:
    """Parse one inclusive date range and reject reversed endpoints."""
    if not isinstance(date_from_value, str) or not isinstance(
        date_to_value,
        str,
    ):
        raise DateRangeValidationError(
            DateRangeValidationReason.INVALID_FORMAT
        )
    try:
        date_from = datetime.strptime(date_from_value, "%Y-%m-%d")
        date_to = datetime.strptime(date_to_value, "%Y-%m-%d").replace(
            hour=23,
            minute=59,
            second=59,
        )
    except ValueError:
        raise DateRangeValidationError(
            DateRangeValidationReason.INVALID_FORMAT
        ) from None

    if date_from > date_to:
        raise DateRangeValidationError(
            DateRangeValidationReason.REVERSED_RANGE
        )
    return date_from, date_to
