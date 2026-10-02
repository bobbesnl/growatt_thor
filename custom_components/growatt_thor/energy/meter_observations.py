"""Unit-aware OCPP meter snapshot used by telemetry consumers."""
from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import TypedDict


class ChargingMeterObservation(TypedDict):
    """Normalized telemetry; missing values remain distinct from zero."""

    power_w: float | None
    currents_a: list[float | None]
    sample_at: str | None


def _number(value: object) -> float | None:
    if not isinstance(value, (str, int, float)):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if isfinite(result) and result >= 0 else None


def charging_meter_values(
    snapshot: Mapping[str, object] | None,
) -> ChargingMeterObservation:
    """Extract current and power with units, preserving missing vs. zero."""
    result: ChargingMeterObservation = {
        "power_w": None,
        "currents_a": [None, None, None],
        "sample_at": None,
    }
    if not snapshot:
        return result
    # Each OCPP entry has its own timestamp. Never blend different entries.
    entries = snapshot.get("meter_values", [])
    if not isinstance(entries, list) or not entries:
        return result
    entry = entries[-1]
    if not isinstance(entry, Mapping):
        return result
    samples = entry.get("sampled_values", [])
    if not isinstance(samples, list):
        return result
    powers: dict[int, float] = {}
    total: float | None = None
    for sample in samples:
        if not isinstance(sample, Mapping):
            continue
        value = _number(sample.get("numeric_value"))
        if value is None:
            continue
        phase = sample.get("phase")
        index = {"L1": 0, "L2": 1, "L3": 2}.get(phase) if isinstance(phase, str) else None
        unit = sample.get("unit")
        if sample.get("measurand") == "Current.Import" and unit in (None, "A"):
            if index is not None:
                result["currents_a"][index] = value
        elif sample.get("measurand") == "Power.Active.Import" and unit in (None, "W", "kW"):
            watts = value * (1000 if unit == "kW" else 1)
            if phase is None:
                total = watts
            elif index is not None:
                powers[index] = watts
    result["power_w"] = (
        total if total is not None else (sum(powers.values()) if len(powers) == 3 else None)
    )
    timestamp = entry.get("timestamp")
    result["sample_at"] = timestamp if isinstance(timestamp, str) else None
    return result
