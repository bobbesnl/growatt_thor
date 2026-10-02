"""Shared normalized site observations for display, accounting and controls."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Literal

from .sources import power_w

BucketQuality = Literal["measured", "derived", "declared", "unknown"]


@dataclass(frozen=True)
class PowerObservation:
    watts: float | None
    observed_at: datetime | None
    max_age_s: int = 120
    quality: BucketQuality = "measured"

    def value_at(self, at: datetime) -> float | None:
        if self.watts is None or not isfinite(self.watts) or self.observed_at is None:
            return None
        if self.observed_at.tzinfo is None or at.tzinfo is None:
            return None
        age = (at - self.observed_at).total_seconds()
        return self.watts if 0 <= age <= self.max_age_s else None


@dataclass(frozen=True)
class SiteObservations:
    grid: PowerObservation | None = None  # positive import
    solar: PowerObservation | None = None  # positive generation
    household: PowerObservation | None = None  # positive non-EV load
    battery: PowerObservation | None = None  # positive discharge
    thermal: PowerObservation | None = None  # positive load
    direct_grid: PowerObservation | None = None
    direct_solar: PowerObservation | None = None


def parse_at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def read_site_observations(coordinator) -> SiteObservations:
    """Read configured site sources; each consumer checks freshness at its clock."""
    options = getattr(coordinator, "site_accounting_options", {}) or {}
    hass = getattr(coordinator, "hass", None)
    states = getattr(hass, "states", None)

    def sensor(key: str, *, sign: int = 1) -> PowerObservation | None:
        entity_id = options.get(key)
        state = states.get(entity_id) if entity_id and states else None
        watts = power_w(state)
        observed = parse_at(getattr(state, "last_updated", None))
        return PowerObservation(watts * sign if watts is not None else None, observed) if entity_id else None

    grid = sensor("site_grid_power_entity", sign=-1 if options.get("site_grid_power_sign") == "positive_export" else 1) if options.get("site_grid_source") == "ha_sensor" else None
    if options.get("site_grid_source") == "thor_external":
        if getattr(coordinator, "external_meter_health", None) == "healthy":
            observed = parse_at(getattr(coordinator, "external_meter_last_updated_at", None))
            grid = PowerObservation(getattr(coordinator, "grid_power", None), observed,
                                    max_age_s=max(15, int(getattr(coordinator, "external_meter_poll_interval", 30)) * 3 + 5))
    battery_entity = getattr(coordinator, "battery_power_entity", None)
    battery = None
    if battery_entity:
        state = states.get(battery_entity) if states else None
        watts = power_w(state)
        if watts is not None and getattr(coordinator, "battery_power_sign", None) == "positive_charge":
            watts = -watts
        battery = PowerObservation(watts, parse_at(getattr(state, "last_updated", None)))
    return SiteObservations(
        grid=grid,
        solar=sensor("site_solar_power_entity"),
        household=sensor("site_house_power_entity"),
        battery=battery,
    )
