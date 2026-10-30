"""Shared normalized site observations for display, accounting and controls."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import datetime
from math import isfinite
from typing import Any, Literal

from ..timestamps import parse_utc
from .contracts import SiteObservationOwner
from .sources import power_w

BucketQuality = Literal["measured", "derived", "declared", "unknown"]


@dataclass(frozen=True, slots=True)
class PowerObservation:
    watts: float | None
    observed_at: datetime | None
    max_age_s: int | None = 120
    quality: BucketQuality = "measured"
    future_tolerance_s: float = 0

    def value_at(self, at: datetime) -> float | None:
        if self.watts is None or not isfinite(self.watts) or self.observed_at is None:
            return None
        if self.observed_at.tzinfo is None or at.tzinfo is None:
            return None
        age = (at - self.observed_at).total_seconds()
        return (
            self.watts
            if age >= -self.future_tolerance_s and (self.max_age_s is None or age <= self.max_age_s)
            else None
        )


@dataclass(frozen=True, slots=True)
class SiteObservations:
    grid: PowerObservation | None = None  # positive import
    solar: PowerObservation | None = None  # positive generation
    household: PowerObservation | None = None  # positive non-EV load
    battery: PowerObservation | None = None  # positive discharge
    thermal: PowerObservation | None = None  # positive load
    direct_grid: PowerObservation | None = None
    direct_solar: PowerObservation | None = None


def align_accounting_observations(
    site: SiteObservations,
    sample_at: datetime,
    received_at: datetime,
) -> SiteObservations:
    """Allow small reporting offsets only within a live meter packet's transit.

    THOR timestamps have whole-second precision; independent HA sensors may be
    reported a fraction of a second later, before the THOR packet arrives. That
    must not discard an otherwise usable source. Keep the original timestamps,
    cap the tolerance at five seconds, and never admit a report beyond receipt.
    Automatic controls and tariff validity do not use this tolerance.
    """
    if sample_at.tzinfo is None or received_at.tzinfo is None:
        return site
    tolerance = min(5.0, (received_at - sample_at).total_seconds())
    if tolerance <= 0:
        return site
    aligned = {}
    for field in fields(site):
        observation = getattr(site, field.name)
        if (
            observation is None
            or observation.observed_at is None
            or observation.observed_at.tzinfo is None
        ):
            continue
        offset = (observation.observed_at - sample_at).total_seconds()
        if 0 < offset <= tolerance:
            aligned[field.name] = replace(observation, future_tolerance_s=offset)
    return replace(site, **aligned) if aligned else site


def parse_at(value: Any) -> datetime | None:
    """Compatibility alias for the shared timezone-aware parser."""
    return parse_utc(value)


def read_site_observations(
    coordinator: SiteObservationOwner, *, require_recent_report: bool = True
) -> SiteObservations:
    """Read site sources, retaining strict report ages for automatic controls.

    HA integrations can suppress writes for unchanged values (often battery 0 W).
    Display/accounting may use those available states until the provider marks
    them unavailable. This does not turn their timestamps into fresh measurements
    or relax the independent THOR meter timeout.
    """
    options = coordinator.site_accounting_options or {}
    hass = coordinator.hass
    states = getattr(hass, "states", None)

    def observation(state, *, sign: int = 1) -> PowerObservation:
        watts = power_w(state)
        attributes = getattr(state, "attributes", {})
        if isinstance(attributes, dict) and attributes.get("restored"):
            watts = None
        observed = parse_at(getattr(state, "last_reported", None)) or parse_at(
            getattr(state, "last_updated", None)
        )
        return PowerObservation(
            watts * sign if watts is not None else None,
            observed,
            max_age_s=120 if require_recent_report else None,
        )

    def sensor(key: str, *, sign: int = 1) -> PowerObservation | None:
        entity_id = options.get(key)
        state = states.get(entity_id) if entity_id and states else None
        return observation(state, sign=sign) if entity_id else None

    grid = (
        sensor(
            "site_grid_power_entity",
            sign=-1 if options.get("site_grid_power_sign") == "positive_export" else 1,
        )
        if options.get("site_grid_source") == "ha_sensor"
        else None
    )
    if options.get("site_grid_source") == "thor_external":
        if coordinator.external_meter_health == "healthy":
            observed = parse_at(coordinator.external_meter_last_updated_at)
            grid = PowerObservation(
                coordinator.grid_power,
                observed,
                max_age_s=max(
                    15,
                    int(coordinator.external_meter_poll_interval) * 3 + 5,
                ),
            )
    battery_entity = coordinator.battery_power_entity
    battery = None
    if battery_entity:
        state = states.get(battery_entity) if states else None
        battery = observation(
            state,
            sign=-1 if coordinator.battery_power_sign == "positive_charge" else 1,
        )
    return SiteObservations(
        grid=grid,
        solar=sensor("site_solar_power_entity"),
        household=sensor("site_house_power_entity"),
        battery=battery,
    )
