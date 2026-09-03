"""Persistent normalized state for the most recent Growatt session."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _record_key(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    transaction_id = _optional_text(value[0])
    end_time = _optional_text(value[1])
    if transaction_id is None or end_time is None:
        return None
    return (transaction_id, end_time)


@dataclass(frozen=True, slots=True)
class LastSessionState:
    """JSON-safe summary backing the existing last-session entities."""

    energy_kwh: float | None = None
    cost: float | None = None
    start_time: str | None = None
    end_time: str | None = None
    plug_time: str | None = None
    unplug_time: str | None = None
    duration_minutes: float | None = None
    session_id: str | None = None
    session_source: str | None = None
    transaction_id: str | None = None
    charge_mode: str | None = None
    work_mode: str | None = None
    record_key: tuple[str, str] | None = None

    @classmethod
    def from_dict(cls, value: Any) -> "LastSessionState":
        """Restore a summary defensively from Home Assistant storage."""
        data = value if isinstance(value, Mapping) else {}
        return cls(
            energy_kwh=_optional_float(data.get("energy_kwh")),
            cost=_optional_float(data.get("cost")),
            start_time=_optional_text(data.get("start_time")),
            end_time=_optional_text(data.get("end_time")),
            plug_time=_optional_text(data.get("plug_time")),
            unplug_time=_optional_text(data.get("unplug_time")),
            duration_minutes=_optional_float(data.get("duration_minutes")),
            session_id=_optional_text(data.get("session_id")),
            session_source=_optional_text(data.get("session_source")),
            transaction_id=_optional_text(data.get("transaction_id")),
            charge_mode=_optional_text(data.get("charge_mode")),
            work_mode=_optional_text(data.get("work_mode")),
            record_key=_record_key(data.get("record_key")),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe storage representation."""
        return {
            "energy_kwh": self.energy_kwh,
            "cost": self.cost,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "plug_time": self.plug_time,
            "unplug_time": self.unplug_time,
            "duration_minutes": self.duration_minutes,
            "session_id": self.session_id,
            "session_source": self.session_source,
            "transaction_id": self.transaction_id,
            "charge_mode": self.charge_mode,
            "work_mode": self.work_mode,
            "record_key": (
                list(self.record_key) if self.record_key is not None else None
            ),
        }
