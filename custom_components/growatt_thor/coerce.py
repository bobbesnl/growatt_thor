"""Small value conversions shared across domain boundaries."""

from __future__ import annotations


def enum_value(value: object, *, stringify_fallback: bool = False):
    """Unwrap enum-like values, preserving each caller's plain-value fallback."""
    if hasattr(value, "value"):
        return value.value
    return str(value) if stringify_fallback else value
