"""Explicit outcomes and transport errors for queued charger commands.

The THOR write queue intentionally separates *running a callback* from the
result of the charger command inside that callback.  A callback can finish
normally after the charger rejected a command, or after the command was
skipped because the connection disappeared.  Keeping those states explicit
prevents misleading "write succeeded" messages and makes reconnect behaviour
possible to reason about from diagnostics a year from now.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite


class ChargerWriteStatus(str, Enum):
    """Result of one logical command submitted to the charger write queue."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    UNCERTAIN = "uncertain"
    EXPIRED = "expired"


class ChargerWriteReconnectPolicy(str, Enum):
    """Decide whether a definitely unsent command may cross a disconnect."""

    RETAIN_UNTIL_EXPIRY = "retain_until_expiry"
    DISCARD_WHEN_DISCONNECTED = "discard_when_disconnected"


@dataclass(frozen=True, slots=True)
class ChargerWriteQueuePolicy:
    """Bound how long an unsent command remains valid in the write queue.

    Expiry applies only before an OCPP request is sent. Once a callback has
    handed its request to OCPP, its acknowledgement or uncertain result must
    still be processed because the charger may already have acted on it.
    """

    expires_after: float
    reconnect: ChargerWriteReconnectPolicy

    def __post_init__(self) -> None:
        if not isfinite(self.expires_after) or self.expires_after <= 0:
            raise ValueError("Write queue expiry must be finite and greater than zero")


# A five-minute window accommodates the THOR's intentional 20-second write
# spacing while ensuring yesterday's automation cannot execute after reconnect.
CONFIGURATION_WRITE_POLICY = ChargerWriteQueuePolicy(
    expires_after=300.0,
    reconnect=ChargerWriteReconnectPolicy.RETAIN_UNTIL_EXPIRY,
)

# Start and AP-mode actions are momentary user intents. They must not survive a
# disconnect and also expire quickly if another active command delays them.
VOLATILE_CONTROL_WRITE_POLICY = ChargerWriteQueuePolicy(
    expires_after=15.0,
    reconnect=ChargerWriteReconnectPolicy.DISCARD_WHEN_DISCONNECTED,
)

# A Stop remains useful across a brief reconnect, but its transaction guard is
# checked again before execution and its lifetime is deliberately short.
TRANSACTION_CONTROL_WRITE_POLICY = ChargerWriteQueuePolicy(
    expires_after=60.0,
    reconnect=ChargerWriteReconnectPolicy.RETAIN_UNTIL_EXPIRY,
)

DEFAULT_WRITE_POLICY = CONFIGURATION_WRITE_POLICY


@dataclass(frozen=True, slots=True)
class ChargerWriteResult:
    """Describe what happened without relying on exceptions or truthiness."""

    status: ChargerWriteStatus
    reason: str | None = None
    charger_result: str | None = None

    @classmethod
    def success(cls, charger_result: object = None) -> "ChargerWriteResult":
        """Return a result for a charger-acknowledged command."""
        return cls(
            ChargerWriteStatus.SUCCESS,
            charger_result=_stringify(charger_result),
        )

    @classmethod
    def failed(
        cls,
        reason: str,
        charger_result: object = None,
    ) -> "ChargerWriteResult":
        """Return a result for a command that definitively did not succeed."""
        return cls(
            ChargerWriteStatus.FAILED,
            reason=reason,
            charger_result=_stringify(charger_result),
        )

    @classmethod
    def skipped(cls, reason: str) -> "ChargerWriteResult":
        """Return a result for a command deliberately not sent."""
        return cls(ChargerWriteStatus.SKIPPED, reason=reason)

    @classmethod
    def uncertain(cls, reason: str) -> "ChargerWriteResult":
        """Return a result whose request may have reached the charger."""
        return cls(ChargerWriteStatus.UNCERTAIN, reason=reason)

    @classmethod
    def expired(cls, reason: str = "expired_before_send") -> "ChargerWriteResult":
        """Return a terminal result for an intent that was never sent."""
        return cls(ChargerWriteStatus.EXPIRED, reason=reason)


class ChargerConnectionUnavailable(RuntimeError):
    """The selected connection became stale before a request was sent."""


class ChargerRequestOutcomeUncertain(RuntimeError):
    """The connection was lost after handing a request to the OCPP layer."""


def _stringify(value: object) -> str | None:
    """Use enum values in diagnostics while still supporting plain strings."""
    if value is None:
        return None
    return str(value.value if hasattr(value, "value") else value)
