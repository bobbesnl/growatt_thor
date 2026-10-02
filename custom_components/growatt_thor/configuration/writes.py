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
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class SupersededConfigurationWriteOutcome:
    """Bounded diagnostic record for a response to an older generation."""

    generation: int
    outcome: str
    result: str | None = None


@dataclass(frozen=True, slots=True)
class ConfigurationWriteState:
    """Last write state retained for one configuration key."""

    key: str
    requested_raw_value: str
    requested_at: str
    generation: int
    status: ConfigurationWriteStatus = ConfigurationWriteStatus.PENDING
    result: str | None = None
    reported_raw_value: str | None = None
    readback_at: str | None = None
    superseded_outcomes: tuple[SupersededConfigurationWriteOutcome, ...] = ()

    def as_dict(self) -> dict[str, object]:
        """Return a diagnostics-friendly representation."""
        data = asdict(self)
        data["status"] = self.status.value
        data["superseded_outcomes"] = [
            asdict(outcome) for outcome in self.superseded_outcomes
        ]
        return data


def begin_configuration_write(
    writes: Mapping[str, ConfigurationWriteState],
    *,
    key: str,
    raw_value: str,
    requested_at: str,
) -> dict[str, ConfigurationWriteState]:
    """Start tracking a write without mutating the previous snapshot.

    A generation belongs to one configuration key and increases for every new
    user intent. Queue deduplication can remove writes that have not started,
    but it cannot cancel an OCPP request already awaiting a response. The
    generation lets that older response identify itself as superseded.
    """
    updated = dict(writes)
    previous = writes.get(key)
    updated[key] = ConfigurationWriteState(
        key=key,
        requested_raw_value=raw_value,
        requested_at=requested_at,
        generation=1 if previous is None else previous.generation + 1,
        superseded_outcomes=(
            () if previous is None else previous.superseded_outcomes
        ),
    )
    return updated


def configuration_write_is_current(
    writes: Mapping[str, ConfigurationWriteState],
    *,
    key: str,
    generation: int,
) -> bool:
    """Return whether an outcome still belongs to the latest user intent."""
    state = writes.get(key)
    return state is not None and state.generation == generation


def acknowledge_configuration_write(
    writes: Mapping[str, ConfigurationWriteState],
    *,
    key: str,
    generation: int,
    accepted: bool,
    result: str,
) -> dict[str, ConfigurationWriteState]:
    """Record the OCPP response while keeping readback separate."""
    state = writes.get(key)
    if state is None:
        return dict(writes)
    if state.generation != generation:
        # An older in-flight request may finish after a newer HA automation has
        # already replaced it. Its response must not overwrite the new intent.
        return _record_superseded_outcome(
            writes,
            key=key,
            generation=generation,
            outcome="accepted" if accepted else "rejected",
            result=result,
        )

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
    generation: int,
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
    if state.generation != generation:
        return _record_superseded_outcome(
            writes,
            key=key,
            generation=generation,
            outcome=status.value,
            result=result,
        )

    updated = dict(writes)
    updated[key] = replace(state, status=status, result=result)
    return updated


def _record_superseded_outcome(
    writes: Mapping[str, ConfigurationWriteState],
    *,
    key: str,
    generation: int,
    outcome: str,
    result: str | None,
) -> dict[str, ConfigurationWriteState]:
    """Append an old outcome without allowing unbounded diagnostics growth."""
    state = writes.get(key)
    if state is None:
        return dict(writes)
    diagnostic = SupersededConfigurationWriteOutcome(
        generation=generation,
        outcome=outcome,
        result=result,
    )
    updated = dict(writes)
    updated[key] = replace(
        state,
        superseded_outcomes=(*state.superseded_outcomes[-4:], diagnostic),
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
