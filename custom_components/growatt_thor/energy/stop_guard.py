"""Pure, transaction-scoped decision for the optional charging stop guard."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Literal

CONF_AUTO_STOP_MODE = "site_auto_stop_mode"
AUTO_STOP_MODES = ("off", "battery", "grid", "battery_or_grid")
CONF_STOP_THRESHOLD = "site_stop_threshold_w"
CONF_STOP_HOLD = "site_stop_hold_seconds"
STOP_THRESHOLD_W = 500.0
STOP_HOLD_SECONDS = 180.0
PV_GRACE_SECONDS = 120.0
StopReason = Literal["battery", "grid"]


def restore_stop_report(value: object) -> dict | None:
    """Retain a small historical explanation, never a restored control intent."""
    if not isinstance(value, dict) or value.get("reason") not in ("battery", "grid"):
        return None
    try:
        at = datetime.fromisoformat(value["at"])
        if at.tzinfo is None:
            return None
        fields = {key: float(value[key]) for key in ("threshold_w", "hold_seconds", "observed_w")}
        if not all(isfinite(number) and number >= 0 for number in fields.values()):
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return {"reason": value["reason"], "at": at.isoformat(), **fields}


@dataclass(frozen=True)
class StopObservation:
    transaction_id: int | None
    eligible: bool
    battery_discharge_w: float | None
    grid_import_w: float | None
    solar_power_w: float | None = None
    ev_power_w: float | None = None


class StopGuardTracker:
    """Require a sustained, fresh observation and fire once per transaction.

    Missing measurements are represented by ``None``. They clear the hold
    window instead of being interpreted as zero or as a stop condition.
    """

    def __init__(self, threshold_w: float = STOP_THRESHOLD_W, hold_seconds: float = STOP_HOLD_SECONDS) -> None:
        self.threshold_w = threshold_w
        self.hold_seconds = hold_seconds
        self.transaction_id: int | None = None
        self.mode = "off"
        self.above_since: datetime | None = None
        self.fired = False

    def required_hold(self, value: StopObservation) -> float:
        """PV covering the EV suggests an extra household load, not free surplus.

        Give such a load two extra minutes, never an unlimited exemption from
        battery protection. Missing PV readings keep the ordinary hold time.
        """
        solar, ev = value.solar_power_w, value.ev_power_w
        covered = (solar is not None and ev is not None and isfinite(solar)
                   and isfinite(ev) and ev > 0 and solar >= ev)
        return self.hold_seconds + (PV_GRACE_SECONDS if covered else 0)

    def evaluate(self, at: datetime, mode: str, value: StopObservation) -> StopReason | None:
        if at.tzinfo is None:
            raise ValueError("Stop guard requires an aware timestamp")
        if mode not in AUTO_STOP_MODES:
            mode = "off"
        if value.transaction_id != self.transaction_id or mode != self.mode:
            self.transaction_id = value.transaction_id
            self.mode = mode
            self.above_since = None
            self.fired = False
        if mode == "off" or not value.eligible or value.transaction_id is None:
            self.above_since = None
            return None

        def above(watts: float | None) -> bool:
            return watts is not None and isfinite(watts) and watts >= self.threshold_w

        battery = mode in ("battery", "battery_or_grid") and above(value.battery_discharge_w)
        grid = mode in ("grid", "battery_or_grid") and above(value.grid_import_w)
        if not battery and not grid:
            self.above_since = None
            return None
        if self.above_since is None or at < self.above_since:
            self.above_since = at
            return None
        if self.fired or (at - self.above_since).total_seconds() < self.required_hold(value):
            return None
        self.fired = True
        return "battery" if battery else "grid"
