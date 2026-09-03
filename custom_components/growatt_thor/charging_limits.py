"""Model-aware charging current limits for Growatt chargers."""
from __future__ import annotations

import re


MIN_CHARGING_CURRENT_A = 6
DEFAULT_MAX_CHARGING_CURRENT_A = 32

_MODEL_CURRENT_LIMITS = (
    (("THOR03AS", "THOR11AS", "EVA11S"), 16),
    (("THOR07AS", "THOR22AS", "EVA22S"), 32),
    (("THOR44AS", "EVA44S"), 63),
)


def maximum_charging_current(*identity_values: object) -> int:
    """Return the safe maximum current for reported model information."""
    limits: list[int] = []

    for value in identity_values:
        if value is None:
            continue
        normalized = re.sub(r"[^A-Z0-9]", "", str(value).upper())
        for markers, limit in _MODEL_CURRENT_LIMITS:
            if any(marker in normalized for marker in markers):
                limits.append(limit)
                break

    # Conflicting identity fields must never broaden the allowed range.
    return min(limits, default=DEFAULT_MAX_CHARGING_CURRENT_A)
