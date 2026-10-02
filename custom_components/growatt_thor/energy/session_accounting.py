"""Bounded, restart-safe accounting checkpoint for one charging transaction."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from typing import Any

from .observations import SiteObservations, parse_at
from .accounting import AccountingPolicy, EVEnergyDelta, Tariff, allocate


BUCKETS = ("direct_solar", "direct_grid", "battery_unknown", "unknown")


@dataclass
class SessionAccumulator:
    transaction_id: str
    meter_start_wh: float | None = None
    last_meter_wh: float | None = None
    last_meter_at: datetime | None = None
    buckets: dict[str, float] = field(default_factory=lambda: {key: 0.0 for key in BUCKETS})
    effective_grid_cost: float = 0.0
    cost_covered: bool = True
    policy_id: str = "grid_first"
    policy_version: int = 1
    policy_topology: str | None = None
    accounting_quality: str = "unknown"
    source: str = "ocpp_meter"
    reset_count: int = 0
    power_fallback_kwh: float = 0.0
    last_power_w: float | None = None
    last_power_at: datetime | None = None

    def observe_power_fallback(self, watts: float, at: datetime) -> bool:
        """Keep an explicitly estimated power integral separate from meter energy."""
        if not isfinite(watts) or watts < 0 or at.tzinfo is None:
            return False
        previous_at, previous_w = self.last_power_at, self.last_power_w
        if previous_at is not None and at <= previous_at:
            return False
        self.last_power_at, self.last_power_w = at, watts
        if previous_at is None or previous_w is None:
            return False
        seconds = (at - previous_at).total_seconds()
        if seconds > 300:
            return False
        # Average power between samples × elapsed seconds gives watt-seconds;
        # dividing by 3,600,000 converts to kWh. This estimate never fills source buckets.
        self.power_fallback_kwh += ((previous_w + watts) / 2) * seconds / 3_600_000
        return True

    def observe(self, *, meter_wh: float, at: datetime, site_id: str, charger_id: str,
                inputs: tuple[SiteObservations, Tariff, AccountingPolicy] | None,
                context: str | None = None, unit: str | None = "Wh") -> bool:
        """Accept only a new transaction meter position in timestamp order."""
        if context == "Transaction.Begin" or unit not in (None, "Wh", "kWh"):
            return False
        meter_wh *= 1000 if unit == "kWh" else 1
        if not isfinite(meter_wh) or meter_wh < 0 or at.tzinfo is None:
            return False
        if self.last_meter_at is not None and at <= self.last_meter_at:
            return False
        previous = self.last_meter_wh
        if previous is None or self.last_meter_at is None:
            self.last_meter_wh, self.last_meter_at = meter_wh, at
            return False
        # A lower counter is a reset, not exported energy. Establish a new
        # baseline instead of booking a negative delta or guessing the missing gap.
        if meter_wh < previous:
            self.reset_count += 1
            self.last_meter_wh, self.last_meter_at = meter_wh, at
            return False
        if meter_wh == previous:
            self.last_meter_at = at
            return False
        delta = EVEnergyDelta(site_id, charger_id, self.transaction_id,
                              self.last_meter_at, at, (meter_wh - previous) / 1000)
        if inputs is None:
            self.buckets["unknown"] += delta.kwh
            self.accounting_quality = "unknown"
        else:
            result = allocate(delta, *inputs)
            policy = inputs[2]
            already_accounted = sum(self.buckets.values()) > 0
            quality_rank = {"measured": 0, "derived": 1, "declared": 2, "unknown": 3}
            self.accounting_quality = (
                max((self.accounting_quality if already_accounted else "measured",
                     result.data_quality.quality), key=lambda value: quality_rank[value])
            )
            for key in BUCKETS:
                self.buckets[key] += getattr(result, key)
            if already_accounted and (self.policy_id != result.policy_id or self.policy_topology != policy.topology):
                self.policy_id = "mixed"
            elif not already_accounted:
                self.policy_id = result.policy_id
                self.policy_topology = policy.topology
            self.policy_version = result.policy_version
            if result.effective_grid_cost is None and result.direct_grid > 0:
                self.cost_covered = False
            elif result.effective_grid_cost is not None:
                self.effective_grid_cost += result.effective_grid_cost
        self.last_meter_wh, self.last_meter_at = meter_wh, at
        return True

    def reconcile(self, authoritative_kwh: float | None) -> None:
        """Book a missing final delta as unknown; trim overcounts without inventing source."""
        if authoritative_kwh is None or not isfinite(authoritative_kwh) or authoritative_kwh < 0:
            return
        total = sum(self.buckets.values())
        difference = authoritative_kwh - total
        if difference > 0.000001:
            self.buckets["unknown"] += difference
            self.accounting_quality = "unknown"
        elif difference < -0.000001 and total:
            if -difference > max(0.01, authoritative_kwh * 0.01):
                self.buckets = {key: 0.0 for key in BUCKETS}
                self.buckets["unknown"] = authoritative_kwh
                self.effective_grid_cost = 0.0
                self.cost_covered = False
                self.accounting_quality = "unknown"
            else:
                ratio = authoritative_kwh / total
                for key in BUCKETS:
                    self.buckets[key] *= ratio
                self.effective_grid_cost *= ratio

    def as_session_dict(self) -> dict:
        total = sum(self.buckets.values())
        known = total - self.buckets["unknown"]
        coverage = known / total if total else 0.0
        return {
            "source_energy_kwh": {key: round(self.buckets[key], 6) for key in BUCKETS},
            "effective_grid_cost": round(self.effective_grid_cost, 6) if self.cost_covered else None,
            "accounting_coverage": round(coverage, 4),
            "accounting_quality": "unknown" if coverage < 0.999999 or self.policy_id == "mixed" else self.accounting_quality,
            "accounting_policy": {"id": self.policy_id, "version": self.policy_version,
                                  "topology": self.policy_topology},
            "green_energy_kwh": round(self.buckets["direct_solar"], 6) if coverage >= 0.999999 and self.policy_id != "mixed" else None,
        }

    def as_dict(self) -> dict:
        return {"transaction_id": self.transaction_id, "meter_start_wh": self.meter_start_wh,
                "last_meter_wh": self.last_meter_wh,
                "last_meter_at": self.last_meter_at.isoformat() if self.last_meter_at else None,
                "buckets": {key: round(self.buckets[key], 9) for key in BUCKETS},
                "effective_grid_cost": self.effective_grid_cost,
                "cost_covered": self.cost_covered, "policy_id": self.policy_id,
                "policy_version": self.policy_version, "policy_topology": self.policy_topology,
                "accounting_quality": self.accounting_quality,
                "reset_count": self.reset_count,
                "power_fallback_kwh": round(self.power_fallback_kwh, 9),
                "last_power_w": self.last_power_w,
                "last_power_at": self.last_power_at.isoformat() if self.last_power_at else None}

    @classmethod
    def from_dict(cls, value: Any) -> SessionAccumulator | None:
        if not isinstance(value, dict) or not value.get("transaction_id"):
            return None
        instance = cls(str(value["transaction_id"]))
        for key in ("meter_start_wh", "last_meter_wh"):
            raw = value.get(key)
            try:
                parsed = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                parsed = None
            setattr(instance, key, parsed if parsed is None or isfinite(parsed) and parsed >= 0 else None)
        instance.last_meter_at = parse_at(value.get("last_meter_at"))
        raw_buckets = value.get("buckets") if isinstance(value.get("buckets"), dict) else {}
        for key in BUCKETS:
            try:
                parsed = float(raw_buckets.get(key, 0))
            except (TypeError, ValueError):
                parsed = 0.0
            instance.buckets[key] = parsed if isfinite(parsed) and parsed >= 0 else 0.0
        try:
            instance.effective_grid_cost = float(value.get("effective_grid_cost", 0))
        except (TypeError, ValueError):
            instance.effective_grid_cost = float("nan")
        valid_cost = isfinite(instance.effective_grid_cost)
        instance.cost_covered = valid_cost and bool(value.get("cost_covered", True))
        if not valid_cost:
            instance.effective_grid_cost = 0.0
        instance.policy_id = str(value.get("policy_id", "grid_first"))
        instance.policy_version = 1
        topology = value.get("policy_topology")
        instance.policy_topology = topology if topology in ("grid_only", "pv", "pv_battery") else None
        quality = value.get("accounting_quality")
        instance.accounting_quality = quality if quality in ("measured", "derived", "declared", "unknown") else "unknown"
        for key in ("power_fallback_kwh", "last_power_w"):
            try:
                parsed = float(value.get(key))
            except (TypeError, ValueError):
                parsed = None
            if parsed is not None and isfinite(parsed) and parsed >= 0:
                setattr(instance, key, parsed)
        instance.last_power_at = parse_at(value.get("last_power_at"))
        return instance
