"""Track accepted configuration writes until the charger reports them back."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import Mapping


class ConfigurationWriteStatus(str, Enum):
    """Lifecycle of one ChangeConfiguration request."""

    PENDING = "pending"
    AWAITING_READBACK = "awaiting_readback"
    CONFIRMED = "confirmed"
    MISMATCH = "mismatch"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ConfigurationWriteState:
    """Last write state retained for one configuration key."""

    key: str
    requested_raw_value: str
    requested_at: str
    status: ConfigurationWriteStatus = ConfigurationWriteStatus.PENDING
    result: str | None = None
    reported_raw_value: str | None = None
    readback_at: str | None = None

    def as_dict(self) -> dict[str, object]:
        """Return a diagnostics-friendly representation."""
        data = asdict(self)
        data["status"] = self.status.value
        return data


def begin_configuration_write(
    writes: Mapping[str, ConfigurationWriteState],
    *,
    key: str,
    raw_value: str,
    requested_at: str,
) -> dict[str, ConfigurationWriteState]:
    """Start tracking a write without mutating the previous snapshot."""
    updated = dict(writes)
    updated[key] = ConfigurationWriteState(
        key=key,
        requested_raw_value=raw_value,
        requested_at=requested_at,
    )
    return updated


def acknowledge_configuration_write(
    writes: Mapping[str, ConfigurationWriteState],
    *,
    key: str,
    accepted: bool,
    result: str,
) -> dict[str, ConfigurationWriteState]:
    """Record the OCPP response while keeping readback separate."""
    state = writes.get(key)
    if state is None:
        return dict(writes)

    updated = dict(writes)
    updated[key] = replace(
        state,
        status=(
            ConfigurationWriteStatus.AWAITING_READBACK
            if accepted
            else ConfigurationWriteStatus.REJECTED
        ),
        result=result,
    )
    return updated


def confirm_configuration_writes(
    writes: Mapping[str, ConfigurationWriteState],
    reported_values: Mapping[str, str | None],
    *,
    readback_at: str,
) -> dict[str, ConfigurationWriteState]:
    """Compare an explicit GetConfiguration response with pending writes."""
    updated = dict(writes)
    for key, reported_raw_value in reported_values.items():
        state = updated.get(key)
        if (
            state is None
            or state.status != ConfigurationWriteStatus.AWAITING_READBACK
        ):
            continue
        updated[key] = replace(
            state,
            status=(
                ConfigurationWriteStatus.CONFIRMED
                if reported_raw_value == state.requested_raw_value
                else ConfigurationWriteStatus.MISMATCH
            ),
            reported_raw_value=reported_raw_value,
            readback_at=readback_at,
        )
    return updated


def serialize_configuration_writes(
    writes: Mapping[str, ConfigurationWriteState],
) -> dict[str, dict[str, object]]:
    """Serialize tracked writes in stable key order."""
    return {key: writes[key].as_dict() for key in sorted(writes)}
