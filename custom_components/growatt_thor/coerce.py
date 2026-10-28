"""Small value conversions shared across domain boundaries."""

from __future__ import annotations

from math import isfinite


def enum_value(value: object, *, stringify_fallback: bool = False):
    """Unwrap enum-like values, preserving each caller's plain-value fallback."""
    if hasattr(value, "value"):
        return value.value
    return str(value) if stringify_fallback else value


def optional_float(
    value: object,
    *,
    finite: bool = True,
    minimum: float | None = None,
    errors: tuple[type[Exception], ...] = (TypeError, ValueError),
) -> float | None:
    """Convert optional numbers without replacing unknown or invalid input by zero."""
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except errors:
        return None
    if finite and not isfinite(number):
        return None
    if minimum is not None and number < minimum:
        return None
    return number


def optional_text(value: object, *, limit: int | None = None) -> str | None:
    """Retain nonempty text, including whitespace, with an optional size bound."""
    if value in (None, ""):
        return None
    text = str(value)
    return text if limit is None else text[:limit]
