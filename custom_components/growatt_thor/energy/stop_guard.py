"""Pure, transaction-scoped decision for the optional charging stop guard."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Literal

CONF_AUTO_STOP_MODE = "site_auto_stop_mode"
AUTO_STOP_MODES = ("off", "battery", "grid", "battery_or_grid")
STOP_THRESHOLD_W = 200.0
STOP_HOLD_SECONDS = 90.0
StopReason = Literal["battery", "grid"]


@dataclass(frozen=True)
class StopObservation:
    transaction_id: int | None
    eligible: bool
    battery_discharge_w: float | None
    grid_import_w: float | None


class StopGuardTracker:
    """Require a sustained, fresh observation and fire once per transaction.

    Missing measurements are represented by ``None``. They clear the hold
    window instead of being interpreted as zero or as a stop condition.
    """

    def __init__(self) -> None:
        self.transaction_id: int | None = None
        self.mode = "off"
        self.above_since: datetime | None = None
        self.fired = False

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
            return watts is not None and isfinite(watts) and watts >= STOP_THRESHOLD_W

        battery = mode in ("battery", "battery_or_grid") and above(value.battery_discharge_w)
        grid = mode in ("grid", "battery_or_grid") and above(value.grid_import_w)
        if not battery and not grid:
            self.above_since = None
            return None
        if self.above_since is None or at < self.above_since:
            self.above_since = at
            return None
        if self.fired or (at - self.above_since).total_seconds() < STOP_HOLD_SECONDS:
            return None
        self.fired = True
        return "battery" if battery else "grid"
