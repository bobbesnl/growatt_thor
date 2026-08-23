"""Parsing for Growatt external-meter DataTransfer payloads."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl


_VOLTAGE_FIELDS = {
    "u-voltage": "L1",
    "v-voltage": "L2",
    "w-voltage": "L3",
}
_CURRENT_FIELDS = {
    "u-current": "L1",
    "v-current": "L2",
    "w-current": "L3",
}


@dataclass(frozen=True)
class ExternalMeterSnapshot:
    """One parsed get_external_meterval response."""

    used: int | None
    wiring: int | None
    power: float | None
    voltages: dict[str, float]
    currents: dict[str, float]


def _optional_int(values: dict[str, str], key: str) -> int | None:
    value = values.get(key)
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _optional_float(values: dict[str, str], key: str) -> float | None:
    value = values.get(key)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_external_meter_data(data: str) -> ExternalMeterSnapshot:
    """Parse the query-string-like Growatt external-meter payload."""
    if not isinstance(data, str):
        raise TypeError("external-meter payload must be a string")

    values = dict(parse_qsl(data, keep_blank_values=True))
    voltages = {
        phase: value
        for key, phase in _VOLTAGE_FIELDS.items()
        if (value := _optional_float(values, key)) is not None
    }
    currents = {
        phase: value
        for key, phase in _CURRENT_FIELDS.items()
        if (value := _optional_float(values, key)) is not None
    }

    return ExternalMeterSnapshot(
        used=_optional_int(values, "used"),
        wiring=_optional_int(values, "wring"),
        power=_optional_float(values, "power"),
        voltages=voltages,
        currents=currents,
    )
