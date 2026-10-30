"""Local PV Linkage draft state; only an explicit Apply writes the charger."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time

from ..configuration.values import ConfigurationValue, configuration_entity_state
from .pv_linkage import (
    PvBoostMode,
    PvLinkageApplyResult,
    PvLinkageDraft,
    parse_manual_period,
)


@dataclass(slots=True)
class PvLinkageDraftState:
    boost_mode: PvBoostMode | None = None
    manual_start: time | None = None
    manual_end: time | None = None
    smart_finish: time | None = None
    smart_target_energy_kwh: float | None = None
    dirty: bool = False
    apply_result: PvLinkageApplyResult | None = None

    def snapshot(self) -> PvLinkageDraft | None:
        """Return the current local PV Linkage draft when initialized."""
        if self.boost_mode is None:
            return None
        return PvLinkageDraft(
            boost_mode=self.boost_mode,
            manual_start=self.manual_start,
            manual_end=self.manual_end,
            smart_finish=self.smart_finish,
            smart_target_energy_kwh=self.smart_target_energy_kwh,
        )

    def initialize(self, configuration_values: Mapping[str, ConfigurationValue]) -> bool:
        """Initialize an untouched draft from reported configuration values."""
        if self.dirty:
            return False

        updated = False
        reported_mode = configuration_entity_state(
            "G_SolarBoost",
            configuration_values.get("G_SolarBoost"),
        )
        if isinstance(reported_mode, str):
            try:
                mode = PvBoostMode(reported_mode)
            except ValueError:
                mode = None
            if mode is not None and self.boost_mode != mode:
                self.boost_mode = mode
                updated = True

        period_value = configuration_values.get("G_PeriodTime")
        period = parse_manual_period(period_value.raw_value if period_value is not None else None)
        if period is not None:
            start, end = period
            if self.manual_start != start:
                self.manual_start = start
                updated = True
            if self.manual_end != end:
                self.manual_end = end
                updated = True

        return updated
