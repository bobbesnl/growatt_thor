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


def charging_power_identity(*identity_values: object) -> dict:
    """Read-only nominal gauge metadata; do not infer wiring from live currents."""
    models = (
        (("THOR03AS",), 1, 3.7),
        (("THOR07AS",), 1, 7.4),
        (("THOR11AS", "EVA11S"), 3, 11.0),
        (("THOR22AS", "EVA22S"), 3, 22.0),
        (("THOR44AS", "EVA44S"), 3, 44.0),
    )
    matches = set()
    for value in identity_values:
        normalized = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
        for markers, phases, power in models:
            if any(marker in normalized for marker in markers):
                matches.add((phases, power))
    # Conflicting or unknown identities are not a reliable display scale.
    if len(matches) != 1:
        return {"nominal_phases": None, "rated_power_kw": None}
    phases, power = matches.pop()
    return {"nominal_phases": phases, "rated_power_kw": power}
