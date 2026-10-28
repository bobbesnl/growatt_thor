"""Bounded persistent state for one active OCPP charging session."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..coerce import optional_float, optional_text
from .events import normalize_session_events
from .series import SESSION_CURVE_POINT_LIMIT, downsample_curve
from .telemetry import context_curves


def _text(value: Any, *, limit: int = 256) -> str | None:
    return optional_text(value, limit=limit)


def _number(value: Any) -> float | None:
    return optional_float(value, minimum=0)


@dataclass(slots=True)
class ActiveSessionState:
    """Minimal session state needed to survive a Home Assistant restart."""

    transaction_id: str | None = None
    id_tag: str | None = None
    id_tag_alias: str | None = None
    start_received_at: str | None = None
    start_timestamp: str | None = None
    connector_id: str | None = None
    meter_start: float | None = None
    energy_wh: float | None = None
    power_curve: list[list[Any]] = field(default_factory=list)
    context_curves: dict = field(default_factory=dict)
    site_house_load_source: str | None = None
    events: list[dict[str, str]] = field(default_factory=list)
    energy_flowing: bool | None = None

    @classmethod
    def from_dict(cls, value: Any) -> ActiveSessionState:
        """Restore only display-safe, bounded fields from storage."""
        data = value if isinstance(value, Mapping) else {}
        energy_flowing = data.get("energy_flowing")
        if not isinstance(energy_flowing, bool):
            energy_flowing = None
        events = normalize_session_events(data.get("events"))
        return cls(
            transaction_id=_text(data.get("transaction_id"), limit=128),
            id_tag=_text(data.get("id_tag")),
            id_tag_alias=_text(data.get("id_tag_alias"), limit=80),
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
            site_house_load_source=data.get("site_house_load_source")
            if data.get("site_house_load_source") in ("configured_sensor", "site_balance", "mixed")
            else None,
            context_curves=context_curves(data, event_times=(event.get("at") for event in events)),
            events=events,
            energy_flowing=energy_flowing,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation for Home Assistant storage."""
        return {
            "transaction_id": self.transaction_id,
            "id_tag": self.id_tag,
            "id_tag_alias": self.id_tag_alias,
            "start_received_at": self.start_received_at,
            "start_timestamp": self.start_timestamp,
            "connector_id": self.connector_id,
            "meter_start": self.meter_start,
            "energy_wh": self.energy_wh,
            "power_curve": self.power_curve,
            **self.context_curves,
            **(
                {"site_house_load_source": self.site_house_load_source}
                if self.site_house_load_source
                else {}
            ),
            "events": self.events,
            "energy_flowing": self.energy_flowing,
        }
