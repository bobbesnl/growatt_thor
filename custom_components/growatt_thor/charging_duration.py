"""Accumulate effective charging time from transaction MeterValues."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from .meter_samples import MeterValue


ACTIVE_POWER_THRESHOLD_W = 100.0
DEFAULT_MAX_SAMPLE_GAP_SECONDS = 180.0


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _watts(value: float, unit: str | None) -> float | None:
    if unit in (None, "W"):
        return value
    if unit == "kW":
        return value * 1000
    return None


def _watt_hours(value: float, unit: str | None) -> float | None:
    if unit in (None, "Wh"):
        return value
    if unit == "kWh":
        return value * 1000
    return None


def _entry_power_w(entry: MeterValue) -> float | None:
    generic: list[float] = []
    phased: dict[str, float] = {}
    for sample in entry.samples:
        if (
            sample.measurand != "Power.Active.Import"
            or sample.numeric_value is None
        ):
            continue
        value = _watts(sample.numeric_value, sample.unit)
        if value is None:
            continue
        if sample.phase is None:
            generic.append(value)
        else:
            phased[sample.phase] = value
    if generic:
        return sum(generic)
    if phased:
        return sum(phased.values())
    return None


def _entry_energy_wh(entry: MeterValue) -> float | None:
    generic: list[float] = []
    phased: dict[str, float] = {}
    for sample in entry.samples:
        if (
            sample.measurand != "Energy.Active.Import.Register"
            or sample.numeric_value is None
        ):
            continue
        value = _watt_hours(sample.numeric_value, sample.unit)
        if value is None:
            continue
        if sample.phase is None:
            generic.append(value)
        else:
            phased[sample.phase] = value
    if generic:
        return max(generic)
    if phased:
        return sum(phased.values())
    return None


@dataclass(slots=True)
class EffectiveChargingTracker:
    """Retain enough sample state to survive Home Assistant restarts."""

    transaction_id: str | None = None
    elapsed_seconds: float = 0.0
    last_sample_at: str | None = None
    last_active: bool = False
    last_energy_wh: float | None = None
    interval_count: int = 0

    def start(self, transaction_id: object) -> None:
        """Start a new transaction unless the restored one already matches."""
        normalized = str(transaction_id)
        if self.transaction_id == normalized:
            return
        self.transaction_id = normalized
        self.elapsed_seconds = 0.0
        self.last_sample_at = None
        self.last_active = False
        self.last_energy_wh = None
        self.interval_count = 0

    def observe(
        self,
        entry: MeterValue,
        *,
        max_gap_seconds: float = DEFAULT_MAX_SAMPLE_GAP_SECONDS,
    ) -> bool:
        """Accumulate one bounded interval and return whether state changed."""
        current_at = _timestamp(entry.timestamp)
        if current_at is None:
            return False

        power_w = _entry_power_w(entry)
        energy_wh = _entry_energy_wh(entry)
        previous_at = _timestamp(self.last_sample_at)
        energy_increased = (
            energy_wh is not None
            and self.last_energy_wh is not None
            and energy_wh > self.last_energy_wh
        )
        changed = False

        if previous_at is not None:
            delta_seconds = (current_at - previous_at).total_seconds()
            if 0 < delta_seconds <= max_gap_seconds:
                self.interval_count += 1
                changed = True
                if self.last_active or energy_increased:
                    self.elapsed_seconds += delta_seconds

        current_active = (
            power_w > ACTIVE_POWER_THRESHOLD_W
            if power_w is not None
            else energy_increased
        )
        current_at_text = current_at.isoformat()
        if self.last_sample_at != current_at_text:
            self.last_sample_at = current_at_text
            changed = True
        if self.last_active != current_active:
            self.last_active = current_active
            changed = True
        if energy_wh is not None and self.last_energy_wh != energy_wh:
            self.last_energy_wh = energy_wh
            changed = True
        return changed

    @property
    def effective_minutes(self) -> float | None:
        """Return a measured duration only after at least one valid interval."""
        if self.interval_count == 0:
            return None
        return round(self.elapsed_seconds / 60, 1)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe persistent representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Any) -> "EffectiveChargingTracker":
        """Restore defensively from an older or partially invalid store."""
        data = value if isinstance(value, dict) else {}
        tracker = cls()
        transaction_id = data.get("transaction_id")
        tracker.transaction_id = (
            str(transaction_id) if transaction_id not in (None, "") else None
        )
        try:
            tracker.elapsed_seconds = max(0.0, float(data.get("elapsed_seconds", 0)))
        except (TypeError, ValueError):
            pass
        tracker.last_sample_at = (
            str(data["last_sample_at"])
            if data.get("last_sample_at") not in (None, "")
            else None
        )
        tracker.last_active = bool(data.get("last_active", False))
        try:
            tracker.last_energy_wh = (
                float(data["last_energy_wh"])
                if data.get("last_energy_wh") not in (None, "")
                else None
            )
        except (TypeError, ValueError):
            tracker.last_energy_wh = None
        try:
            tracker.interval_count = max(0, int(data.get("interval_count", 0)))
        except (TypeError, ValueError):
            pass
        return tracker
