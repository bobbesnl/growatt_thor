"""Lossless models for OCPP 1.6 MeterValues payloads."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_MEASURAND = "Energy.Active.Import.Register"


def _json_safe(value: Any) -> Any:
    """Convert OCPP model values into JSON-safe diagnostic data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "__dict__"):
        return {
            str(key): _json_safe(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
    return str(value)


def _field(value: Any, *names: str) -> Any:
    """Read the first matching dictionary key or object attribute."""
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return None

    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return None


def _text(value: Any) -> str | None:
    """Normalize an optional enum or scalar to text."""
    if value is None:
        return None
    if isinstance(value, Enum):
        value = value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _numeric(value: Any) -> float | None:
    """Parse a numeric sample without discarding its raw representation."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_sequence(value: Any) -> tuple[Any, ...]:
    """Normalize one OCPP collection field to a tuple."""
    if value is None:
        return ()
    if isinstance(value, Mapping) or isinstance(value, (str, bytes)):
        return (value,)
    if isinstance(value, Iterable):
        return tuple(value)
    return (value,)


@dataclass(frozen=True, slots=True)
class MeterSample:
    """One OCPP SampledValue with both raw and normalized fields."""

    raw_value: str | None
    numeric_value: float | None
    measurand: str
    unit: str | None
    phase: str | None
    context: str | None
    location: str | None
    value_format: str | None
    raw: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe diagnostic representation."""
        return {
            "value": self.raw_value,
            "numeric_value": self.numeric_value,
            "measurand": self.measurand,
            "unit": self.unit,
            "phase": self.phase,
            "context": self.context,
            "location": self.location,
            "format": self.value_format,
            "raw": self.raw,
        }


@dataclass(frozen=True, slots=True)
class MeterValue:
    """One timestamped OCPP MeterValue entry."""

    timestamp: str | None
    samples: tuple[MeterSample, ...]
    raw: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe diagnostic representation."""
        return {
            "timestamp": self.timestamp,
            "sampled_values": [sample.as_dict() for sample in self.samples],
            "raw": self.raw,
        }


def _parse_sample(sample: Any) -> MeterSample:
    """Parse one SampledValue object or dictionary."""
    raw_value = _field(sample, "value")
    measurand = _text(_field(sample, "measurand")) or DEFAULT_MEASURAND
    raw = _json_safe(sample)
    if not isinstance(raw, dict):
        raw = {"value": raw}

    return MeterSample(
        raw_value=_text(raw_value),
        numeric_value=_numeric(raw_value),
        measurand=measurand,
        unit=_text(_field(sample, "unit")),
        phase=_text(_field(sample, "phase")),
        context=_text(_field(sample, "context")),
        location=_text(_field(sample, "location")),
        value_format=_text(_field(sample, "format", "value_format")),
        raw=raw,
    )


def normalize_meter_timestamp(value: str | None, time_zone: str | None = None) -> str | None:
    """Convert THOR local wall-clock timestamps to UTC without guessing DST folds.

    Some firmware omits the UTC offset. Only HA's configured installation zone
    can resolve those values; the process/browser timezone and receipt time
    must never turn an old or ambiguous sample into a current observation.
    """
    if not value or not isinstance(value, str) or "T" not in value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if not time_zone:
        return None
    try:
        zone = ZoneInfo(time_zone)
    except (ValueError, ZoneInfoNotFoundError):
        return None
    # Round trips reject nonexistent spring times; two distinct UTC candidates
    # identify an ambiguous autumn time. Explicit offsets above need no guess.
    candidates = set()
    for fold in (0, 1):
        utc = parsed.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None) == parsed:
            candidates.add(utc)
    if len(candidates) != 1:
        return None
    return candidates.pop().isoformat().replace("+00:00", "Z")


def parse_meter_values(payload: Any, *, time_zone: str | None = None) -> tuple[MeterValue, ...]:
    """Parse OCPP MeterValues entries without dropping unknown fields."""
    meter_values = []
    for entry in _as_sequence(payload):
        sampled_values = _field(entry, "sampled_value", "sampledValue")
        raw = _json_safe(entry)
        if not isinstance(raw, dict):
            raw = {"value": raw}

        meter_values.append(
            MeterValue(
                timestamp=normalize_meter_timestamp(_text(_field(entry, "timestamp")), time_zone),
                samples=tuple(
                    _parse_sample(sample)
                    for sample in _as_sequence(sampled_values)
                ),
                raw=raw,
            )
        )

    return tuple(meter_values)


def charging_power_curve_point(entry: MeterValue) -> list[Any] | None:
    """Return one total charging-power point without filling missing phases."""
    if not entry.timestamp:
        return None
    total = None
    phases = []
    for sample in entry.samples:
        if sample.measurand != "Power.Active.Import" or sample.numeric_value is None:
            continue
        if (
            sample.unit not in (None, "W", "kW")
            or sample.numeric_value < 0
            or not isfinite(sample.numeric_value)
        ):
            continue
        watts = sample.numeric_value * (1000 if sample.unit == "kW" else 1)
        if sample.phase is None:
            total = watts
        else:
            phases.append(watts)
    if total is None:
        total = sum(phases) if phases else None
    return [entry.timestamp, round(total, 1)] if total is not None else None
