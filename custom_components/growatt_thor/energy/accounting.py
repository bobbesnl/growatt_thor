"""Deterministic, Home Assistant independent site EV accounting.

Power observations describe the same time interval as the authoritative EV delta.
A priority is a declared booking policy, never evidence of electron provenance.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Literal

TOLERANCE_KWH = 1e-6
POLICY_VERSION = 1
from .observations import BucketQuality, PowerObservation, SiteObservations


@dataclass(frozen=True)
class EVEnergyDelta:
    site_id: str
    charger_id: str
    transaction_id: str
    start_at: datetime
    end_at: datetime
    kwh: float
    source: Literal["ocpp_meter", "ocpp_stop", "growatt_record", "power_fallback"] = "ocpp_meter"

    @property
    def hours(self) -> float:
        return max(0.0, (self.end_at - self.start_at).total_seconds() / 3600)


@dataclass(frozen=True)
class Tariff:
    price_per_kwh: float | None
    currency: str = "EUR"
    observed_at: datetime | None = None
    max_age_s: int | None = 3600
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    def price_at(self, at: datetime) -> float | None:
        if self.price_per_kwh is None or not isfinite(self.price_per_kwh):
            return None
        if at.tzinfo is None:
            return None
        if self.valid_from is not None and (self.valid_from.tzinfo is None or at < self.valid_from):
            return None
        if self.valid_to is not None and (self.valid_to.tzinfo is None or at >= self.valid_to):
            return None
        if self.observed_at is None:
            return self.price_per_kwh  # fixed tariff
        if self.observed_at.tzinfo is None or at.tzinfo is None:
            return None
        age = (at - self.observed_at).total_seconds()
        return self.price_per_kwh if age >= 0 and (self.max_age_s is None or age <= self.max_age_s) else None


@dataclass(frozen=True)
class AccountingPolicy:
    policy_id: Literal["grid_first", "load_first"] = "grid_first"
    policy_version: int = POLICY_VERSION
    topology: Literal["grid_only", "pv", "pv_battery"] = "grid_only"


@dataclass(frozen=True)
class DataQuality:
    quality: BucketQuality
    coverage: float
    missing: tuple[str, ...] = ()


@dataclass(frozen=True)
class Allocation:
    direct_solar: float
    direct_grid: float
    battery_unknown: float
    unknown: float
    effective_grid_cost: float | None
    data_quality: DataQuality
    policy_id: str
    policy_version: int

    def as_session_dict(self) -> dict:
        return {
            "source_energy_kwh": {
                "direct_solar": self.direct_solar,
                "direct_grid": self.direct_grid,
                "battery_unknown": self.battery_unknown,
                "unknown": self.unknown,
            },
            "effective_grid_cost": self.effective_grid_cost,
            "accounting_coverage": self.data_quality.coverage,
            "accounting_quality": self.data_quality.quality,
            "accounting_policy": {"id": self.policy_id, "version": self.policy_version},
        }


def allocate(delta: EVEnergyDelta, site: SiteObservations, tariff: Tariff,
             policy: AccountingPolicy) -> Allocation:
    """Allocate one positive EV meter delta; unproven residual remains unknown."""
    if not isfinite(delta.kwh) or delta.kwh < 0 or delta.hours <= 0:
        raise ValueError("EV delta and interval must be positive and finite")
    remaining = delta.kwh
    missing: list[str] = []
    measured = False

    def energy(name: str, observation: PowerObservation | None) -> float | None:
        nonlocal measured
        value = observation.value_at(delta.end_at) if observation else None
        if value is None:
            missing.append(name)
            return None
        if value < 0 and name not in ("grid", "battery"):
            missing.append(name)
            return None
        measured = True
        return max(0.0, value) * delta.hours / 1000

    direct_grid = energy("direct_grid", site.direct_grid) if site.direct_grid else None
    direct_solar = energy("direct_solar", site.direct_solar) if site.direct_solar else None
    grid = energy("grid", site.grid) if policy.topology != "grid_only" else None
    solar = energy("solar", site.solar) if policy.topology != "grid_only" else None
    household = energy("household", site.household) if site.household and policy.topology != "grid_only" else None
    if household is None and policy.policy_id == "load_first" and policy.topology != "grid_only" and "household" not in missing:
        missing.append("household")
    battery = energy("battery", site.battery) if policy.topology == "pv_battery" else None
    battery_charge = None
    if policy.topology == "pv_battery" and site.battery:
        value = site.battery.value_at(delta.end_at)
        battery_charge = max(0.0, -value) * delta.hours / 1000 if value is not None else None
    grid_kwh = solar_kwh = battery_kwh = 0.0

    # Explicit directed measurements always win over a declared priority.
    if direct_grid is not None:
        grid_kwh = min(remaining, direct_grid)
        remaining -= grid_kwh
    if direct_solar is not None:
        solar_kwh = min(remaining, direct_solar)
        remaining -= solar_kwh

    if policy.topology == "grid_only":
        grid_kwh += remaining
        remaining = 0.0
    else:
        if policy.policy_id == "load_first":
            # The measured PV supply is booked to household and battery charge
            # before EVSE. Thermal load follows EVSE and cannot reduce its share.
            available_solar = (
                max(0.0, solar - household - (battery_charge or 0.0))
                if solar is not None and household is not None
                and (policy.topology != "pv_battery" or battery_charge is not None)
                else None
            )
        else:
            available_solar = (
                max(0.0, solar - (household or 0.0) - (battery_charge or 0.0))
                if solar is not None and (policy.topology != "pv_battery" or battery_charge is not None)
                else None
            )
        if policy.policy_id == "load_first" and direct_solar is None and available_solar is not None and grid is not None:
            solar_share = min(remaining, available_solar)
            solar_kwh += solar_share
            remaining -= solar_share
        if direct_grid is None and grid is not None:
            grid_share = min(remaining, grid)
            grid_kwh += grid_share
            remaining -= grid_share
        if battery is not None and grid is not None:
            battery_kwh = min(remaining, battery)
            remaining -= battery_kwh
        if policy.policy_id == "grid_first" and direct_solar is None and available_solar is not None and grid is not None:
            solar_share = min(remaining, available_solar)
            solar_kwh += solar_share
            remaining -= solar_share
    unknown = max(0.0, remaining)
    # Clamp floating arithmetic and keep the balance exact.
    unknown = max(0.0, delta.kwh - grid_kwh - solar_kwh - battery_kwh)
    coverage = max(0.0, min(1.0, (delta.kwh - unknown) / delta.kwh)) if delta.kwh else 1.0
    quality: BucketQuality = "unknown" if unknown > TOLERANCE_KWH else (
        "measured" if direct_grid is not None or direct_solar is not None else
        "declared" if policy.policy_id == "load_first" or policy.topology == "grid_only" else
        "derived" if measured else "unknown"
    )
    price = tariff.price_at(delta.end_at)
    cost = grid_kwh * price if price is not None else None
    return Allocation(solar_kwh, grid_kwh, battery_kwh, unknown, cost,
                      DataQuality(quality, coverage, tuple(missing)),
                      policy.policy_id, policy.policy_version)


def split_parallel(total: Allocation, deltas: tuple[EVEnergyDelta, ...]) -> tuple[Allocation, ...]:
    """Share a site allocation proportionally, without counting a site meter twice."""
    total_kwh = sum(delta.kwh for delta in deltas)
    if total_kwh <= 0:
        return ()
    if abs(total_kwh - sum((total.direct_solar, total.direct_grid,
                            total.battery_unknown, total.unknown))) > TOLERANCE_KWH:
        raise ValueError("Site allocation does not match charger deltas")
    def share(delta: EVEnergyDelta) -> Allocation:
        ratio = delta.kwh / total_kwh
        return Allocation(total.direct_solar * ratio, total.direct_grid * ratio,
                          total.battery_unknown * ratio, total.unknown * ratio,
                          total.effective_grid_cost * ratio if total.effective_grid_cost is not None else None,
                          total.data_quality, total.policy_id, total.policy_version)
    return tuple(share(delta) for delta in deltas)
