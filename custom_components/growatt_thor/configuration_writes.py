"""Track accepted configuration writes until the charger reports them back."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Mapping


class ConfigurationWriteStatus(str, Enum):
    """Lifecycle of one ChangeConfiguration request."""

    PENDING = "pending"
    AWAITING_READBACK = "awaiting_readback"
    CONFIRMED = "confirmed"
    MISMATCH = "mismatch"
    REJECTED = "rejected"
    SKIPPED = "skipped"
    UNCERTAIN = "uncertain"


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


def mark_configuration_write(
    writes: Mapping[str, ConfigurationWriteState],
    *,
    key: str,
    status: ConfigurationWriteStatus,
    result: str | None = None,
) -> dict[str, ConfigurationWriteState]:
    """Record a non-acknowledgement outcome for an existing write.

    Transport loss is deliberately not represented as ``REJECTED``.  Once a
    ChangeConfiguration request has entered the OCPP layer, a disconnect does
    not tell us whether the THOR applied it before the socket disappeared.
    ``UNCERTAIN`` therefore remains eligible for reconciliation by the next
    GetConfiguration response.
    """
    state = writes.get(key)
    if state is None:
        return dict(writes)

    updated = dict(writes)
    updated[key] = replace(state, status=status, result=result)
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
            or state.status
            not in {
                ConfigurationWriteStatus.AWAITING_READBACK,
                ConfigurationWriteStatus.UNCERTAIN,
            }
        ):
            continue
        updated[key] = replace(
            state,
            status=(
                ConfigurationWriteStatus.CONFIRMED
                if _raw_values_match(
                    state.requested_raw_value,
                    reported_raw_value,
                )
                else ConfigurationWriteStatus.MISMATCH
            ),
            reported_raw_value=reported_raw_value,
            readback_at=readback_at,
        )
    return updated


def pending_configuration_value(
    writes: Mapping[str, ConfigurationWriteState],
    key: str,
) -> str | None:
    """Return the desired value while the charger outcome is still unresolved.

    Entities such as the LCD switch should show the user's newly requested
    state while it waits in the rate-limited queue.  A rejected, skipped, or
    mismatching write is deliberately excluded so the entity falls back to the
    last value actually reported by the THOR.
    """
    state = writes.get(key)
    if state is None or state.status not in {
        ConfigurationWriteStatus.PENDING,
        ConfigurationWriteStatus.AWAITING_READBACK,
        ConfigurationWriteStatus.UNCERTAIN,
    }:
        return None
    return state.requested_raw_value


def _raw_values_match(requested: str, reported: str | None) -> bool:
    """Compare wire values without treating harmless number formatting as drift.

    The THOR commonly acknowledges ``13`` and later reports ``13.00``.  Exact
    string comparison would mark that successful write as a mismatch.  Only
    values that are both plain decimals receive numeric comparison; compound
    vendor payloads such as ``1&Enable`` remain exact and case-sensitive.
    """
    if reported is None:
        return False
    if requested == reported:
        return True
    try:
        return Decimal(requested.strip()) == Decimal(reported.strip())
    except (InvalidOperation, AttributeError, ValueError):
        return False


def serialize_configuration_writes(
    writes: Mapping[str, ConfigurationWriteState],
) -> dict[str, dict[str, object]]:
    """Serialize tracked writes in stable key order."""
    return {key: writes[key].as_dict() for key in sorted(writes)}
