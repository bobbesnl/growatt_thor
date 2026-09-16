"""Validated compound writes for Growatt PV Linkage boost controls."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from enum import Enum
import re


class PvBoostMode(str, Enum):
    """PV Linkage boost modes confirmed in Growatt captures."""

    DISABLED = "disabled"
    MANUAL = "manual"
    SMART = "smart"


class PvLinkageApplyStatus(str, Enum):
    """Overall result of one logical PV Linkage Apply operation."""

    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class PvLinkageApplyResult:
    """Retain compound progress without claiming transactional OCPP writes.

    Growatt exposes the logical Apply operation as multiple independent OCPP
    requests.  ``completed_steps`` therefore describes acknowledged physical
    steps, while ``status`` tells Home Assistant whether the whole draft was
    applied, rejected before any change, partially applied, or left uncertain.
    """

    status: PvLinkageApplyStatus
    completed_steps: int
    total_steps: int
    failed_step: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.total_steps <= 0:
            raise ValueError("Compound apply must contain at least one step")
        if not 0 <= self.completed_steps <= self.total_steps:
            raise ValueError("Completed steps must fit within total steps")
        if (
            self.status == PvLinkageApplyStatus.SUCCESS
            and self.completed_steps != self.total_steps
        ):
            raise ValueError("Successful apply must complete every step")

    @classmethod
    def success(cls, total_steps: int) -> "PvLinkageApplyResult":
        return cls(
            status=PvLinkageApplyStatus.SUCCESS,
            completed_steps=total_steps,
            total_steps=total_steps,
        )

    @classmethod
    def failed(
        cls,
        *,
        completed_steps: int,
        total_steps: int,
        failed_step: str,
        reason: object,
    ) -> "PvLinkageApplyResult":
        return cls(
            status=(
                PvLinkageApplyStatus.PARTIAL
                if completed_steps
                else PvLinkageApplyStatus.FAILED
            ),
            completed_steps=completed_steps,
            total_steps=total_steps,
            failed_step=failed_step,
            reason=_outcome_text(reason),
        )

    @classmethod
    def uncertain(
        cls,
        *,
        completed_steps: int,
        total_steps: int,
        failed_step: str,
        reason: object,
    ) -> "PvLinkageApplyResult":
        return cls(
            status=PvLinkageApplyStatus.UNCERTAIN,
            completed_steps=completed_steps,
            total_steps=total_steps,
            failed_step=failed_step,
            reason=_outcome_text(reason),
        )

    def as_dict(self) -> dict[str, object]:
        """Return a diagnostics- and entity-attribute-friendly snapshot."""
        data = asdict(self)
        data["status"] = self.status.value
        return data


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


def _outcome_text(value: object) -> str:
    """Normalize enum and exception details for stable diagnostics."""
    return str(value.value if hasattr(value, "value") else value)


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


def draft_matches_reported(
    draft: PvLinkageDraft,
    *,
    reported_mode: str | None,
    reported_period: str | None,
) -> bool:
    """Return whether all readable parts already match the charger."""
    try:
        mode = PvBoostMode(reported_mode) if reported_mode is not None else None
    except ValueError:
        return False
    if draft.boost_mode != mode:
        return False
    if draft.boost_mode == PvBoostMode.DISABLED:
        return True
    if draft.boost_mode == PvBoostMode.MANUAL:
        period = parse_manual_period(reported_period)
        return period == (draft.manual_start, draft.manual_end)

    # Smart target data is sent via DataTransfer and has no independent readback.
    return False


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
