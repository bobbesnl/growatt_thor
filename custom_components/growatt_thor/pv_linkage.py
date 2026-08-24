"""Validated compound writes for Growatt PV Linkage boost controls."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import Enum
import re


class PvBoostMode(str, Enum):
    """PV Linkage boost modes confirmed in Growatt captures."""

    DISABLED = "disabled"
    MANUAL = "manual"
    SMART = "smart"


@dataclass(frozen=True, slots=True)
class PvLinkageDraft:
    """One local PV Linkage draft awaiting explicit application."""

    boost_mode: PvBoostMode
    manual_start: time | None = None
    manual_end: time | None = None
    smart_finish: time | None = None
    smart_target_energy_kwh: float | None = None


@dataclass(frozen=True, slots=True)
class ConfigurationWrite:
    """One ChangeConfiguration operation in a compound update."""

    key: str
    value: str


@dataclass(frozen=True, slots=True)
class DataTransferWrite:
    """One vendor DataTransfer operation in a compound update."""

    vendor_id: str
    message_id: str
    data: str


PvLinkageWrite = ConfigurationWrite | DataTransferWrite

_PERIOD_PATTERN = re.compile(
    r"(?:^|&)time1=(?P<start>\d{2}:\d{2})-(?P<end>\d{2}:\d{2})(?:&|$)"
)


def parse_manual_period(raw_value: str | None) -> tuple[time, time] | None:
    """Parse the first Manual Boost period from ``G_PeriodTime``."""
    if not raw_value:
        return None
    match = _PERIOD_PATTERN.search(raw_value)
    if match is None:
        return None
    try:
        return (
            time.fromisoformat(match.group("start")),
            time.fromisoformat(match.group("end")),
        )
    except ValueError:
        return None


def draft_validation_errors(draft: PvLinkageDraft) -> tuple[str, ...]:
    """Return stable validation codes for the selected boost mode."""
    errors: list[str] = []
    if draft.boost_mode == PvBoostMode.MANUAL:
        if draft.manual_start is None:
            errors.append("manual_start_required")
        if draft.manual_end is None:
            errors.append("manual_end_required")
    elif draft.boost_mode == PvBoostMode.SMART:
        if draft.smart_finish is None:
            errors.append("smart_finish_required")
        if (
            draft.smart_target_energy_kwh is None
            or draft.smart_target_energy_kwh <= 0
        ):
            errors.append("smart_target_energy_required")
    return tuple(errors)


def _format_number(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def next_finish_at(now: datetime, finish: time) -> datetime:
    """Resolve a time-of-day to its next occurrence in ``now``'s timezone."""
    candidate = datetime.combine(now.date(), finish, tzinfo=now.tzinfo)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def build_pv_linkage_writes(
    draft: PvLinkageDraft,
    *,
    now: datetime,
    connector_id: int = 1,
) -> tuple[PvLinkageWrite, ...]:
    """Build the captured atomic write sequence for one validated draft."""
    errors = draft_validation_errors(draft)
    if errors:
        raise ValueError(", ".join(errors))

    if draft.boost_mode == PvBoostMode.DISABLED:
        return (ConfigurationWrite("G_SolarBoost", "1&Disable"),)

    if draft.boost_mode == PvBoostMode.MANUAL:
        assert draft.manual_start is not None
        assert draft.manual_end is not None
        period = (
            f"1&time1={draft.manual_start.strftime('%H:%M')}-"
            f"{draft.manual_end.strftime('%H:%M')}"
        )
        return (
            ConfigurationWrite("G_SolarBoost", "1&ManualBoost"),
            ConfigurationWrite("G_PeriodTime", period),
        )

    assert draft.smart_finish is not None
    assert draft.smart_target_energy_kwh is not None
    finish_at = next_finish_at(now, draft.smart_finish)
    data = (
        f"connectorid={connector_id}"
        f"&contime={finish_at.strftime('%Y-%m-%d %H:%M')}"
        f"&energy={_format_number(draft.smart_target_energy_kwh)}"
    )
    return (
        ConfigurationWrite("G_SolarBoost", "1&SmartBoost"),
        DataTransferWrite("Growatt", "solar_target_data", data),
    )
