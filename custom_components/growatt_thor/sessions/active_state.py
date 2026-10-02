"""Bounded persistent state for one active OCPP charging session."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from typing import Any

from .events import normalize_session_events
from .series import SESSION_CURVE_POINT_LIMIT, downsample_curve


def _text(value: Any, *, limit: int = 256) -> str | None:
    if value in (None, ""):
        return None
    return str(value)[:limit]


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) and result >= 0 else None


@dataclass(slots=True)
class ActiveSessionState:
    """Minimal session state needed to survive a Home Assistant restart."""

    transaction_id: str | None = None
    id_tag: str | None = None
    start_received_at: str | None = None
    start_timestamp: str | None = None
    connector_id: str | None = None
    meter_start: float | None = None
    energy_wh: float | None = None
    power_curve: list[list[Any]] = field(default_factory=list)
    events: list[dict[str, str]] = field(default_factory=list)
    energy_flowing: bool | None = None

    @classmethod
    def from_dict(cls, value: Any) -> "ActiveSessionState":
        """Restore only display-safe, bounded fields from storage."""
        data = value if isinstance(value, Mapping) else {}
        energy_flowing = data.get("energy_flowing")
        if not isinstance(energy_flowing, bool):
            energy_flowing = None
        events = normalize_session_events(data.get("events"))
        return cls(
            transaction_id=_text(data.get("transaction_id"), limit=128),
            id_tag=_text(data.get("id_tag")),
            start_received_at=_text(data.get("start_received_at")),
            start_timestamp=_text(data.get("start_timestamp")),
            connector_id=_text(data.get("connector_id"), limit=64),
            meter_start=_number(data.get("meter_start")),
            energy_wh=_number(data.get("energy_wh")),
            power_curve=downsample_curve(
                data.get("power_curve"),
                limit=SESSION_CURVE_POINT_LIMIT,
                event_times=(event.get("at") for event in events),
            ),
            events=events,
            energy_flowing=energy_flowing,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation for Home Assistant storage."""
        return {
            "transaction_id": self.transaction_id,
            "id_tag": self.id_tag,
            "start_received_at": self.start_received_at,
            "start_timestamp": self.start_timestamp,
            "connector_id": self.connector_id,
            "meter_start": self.meter_start,
            "energy_wh": self.energy_wh,
            "power_curve": self.power_curve,
            "events": self.events,
            "energy_flowing": self.energy_flowing,
        }
