"""Lossless models for OCPP 1.6 MeterValues payloads."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any


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


def parse_meter_values(payload: Any) -> tuple[MeterValue, ...]:
    """Parse OCPP MeterValues entries without dropping unknown fields."""
    meter_values = []
    for entry in _as_sequence(payload):
        sampled_values = _field(entry, "sampled_value", "sampledValue")
        raw = _json_safe(entry)
        if not isinstance(raw, dict):
            raw = {"value": raw}

        meter_values.append(
            MeterValue(
                timestamp=_text(_field(entry, "timestamp")),
                samples=tuple(
                    _parse_sample(sample)
                    for sample in _as_sequence(sampled_values)
                ),
                raw=raw,
            )
        )

    return tuple(meter_values)
