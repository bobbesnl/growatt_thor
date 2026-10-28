"""Normalize OCPP 1.6 charge point statuses for Home Assistant entities."""

from __future__ import annotations

from typing import Final

from ..coerce import enum_value

ENERGY_SESSION_STATUSES = frozenset({"charging", "suspended_ev", "suspended_evse"})
LIVE_POWER_STATUSES = frozenset({"charging"})

OCPP_STATUS_OPTIONS: Final[tuple[str, ...]] = (
    "available",
    "preparing",
    "charging",
    "suspended_evse",
    "suspended_ev",
    "finishing",
    "reserved",
    "unavailable",
    "faulted",
    "idle",
)

_OCPP_STATUS_ALIASES: Final[dict[str, str]] = {
    "available": "available",
    "preparing": "preparing",
    "charging": "charging",
    "suspendedevse": "suspended_evse",
    "suspendedev": "suspended_ev",
    "finishing": "finishing",
    "reserved": "reserved",
    "unavailable": "unavailable",
    "faulted": "faulted",
    "idle": "idle",
}


def normalize_ocpp_status(status: object | None) -> str | None:
    """Return a translation-safe state for an OCPP status value."""
    if status is None:
        return None

    value = enum_value(status, stringify_fallback=True)
    normalized = "".join(character for character in str(value).casefold() if character.isalnum())
    return _OCPP_STATUS_ALIASES.get(normalized)
