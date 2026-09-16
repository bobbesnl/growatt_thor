"""Explicit outcomes and transport errors for queued charger commands.

The THOR write queue intentionally separates *running a callback* from the
result of the charger command inside that callback.  A callback can finish
normally after the charger rejected a command, or after the command was
skipped because the connection disappeared.  Keeping those states explicit
prevents misleading "write succeeded" messages and makes reconnect behaviour
possible to reason about from diagnostics a year from now.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from uuid import uuid4


class ChargerWriteStatus(str, Enum):
    """Result of one logical command submitted to the charger write queue."""

    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    SKIPPED = "skipped"
    UNCERTAIN = "uncertain"
    EXPIRED = "expired"


class ChargerCommandStatus(str, Enum):
    """Stable terminal states exposed to Home Assistant automations."""

    CONFIRMED = "confirmed"
    FAILED = "failed"
    SKIPPED = "skipped"
    EXPIRED = "expired"
    UNCERTAIN = "uncertain"


COMMAND_COMPLETION_STATUSES = tuple(status.value for status in ChargerCommandStatus)


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
    def partial(
        cls,
        reason: str,
        charger_result: object = None,
    ) -> "ChargerWriteResult":
        """Return a result when only part of a compound command succeeded."""
        return cls(
            ChargerWriteStatus.PARTIAL,
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


@dataclass(frozen=True, slots=True)
class ChargerCommandResult:
    """Public terminal result correlated by one immutable command ID."""

    command_id: str
    command_name: str
    status: ChargerCommandStatus
    write_status: ChargerWriteStatus
    queued_at: str
    completed_at: str
    reason: str | None = None
    charger_result: str | None = None

    @classmethod
    def from_write_result(
        cls,
        *,
        command_id: str,
        command_name: str,
        queued_at: str,
        completed_at: str,
        result: ChargerWriteResult,
    ) -> "ChargerCommandResult":
        """Map queue-internal detail to the stable automation contract."""
        status = {
            ChargerWriteStatus.SUCCESS: ChargerCommandStatus.CONFIRMED,
            ChargerWriteStatus.FAILED: ChargerCommandStatus.FAILED,
            ChargerWriteStatus.SKIPPED: ChargerCommandStatus.SKIPPED,
            ChargerWriteStatus.EXPIRED: ChargerCommandStatus.EXPIRED,
            ChargerWriteStatus.UNCERTAIN: ChargerCommandStatus.UNCERTAIN,
            # A compound partial write cannot be called confirmed.  Preserve
            # ``write_status=partial`` for diagnostics while exposing the safe
            # terminal automation outcome as uncertain.
            ChargerWriteStatus.PARTIAL: ChargerCommandStatus.UNCERTAIN,
        }[result.status]
        return cls(
            command_id=command_id,
            command_name=command_name,
            status=status,
            write_status=result.status,
            queued_at=queued_at,
            completed_at=completed_at,
            reason=result.reason,
            charger_result=result.charger_result,
        )

    def as_dict(self) -> dict[str, str | None]:
        """Return a JSON-safe representation for entities and diagnostics."""
        return {
            "command_id": self.command_id,
            "command_name": self.command_name,
            "status": self.status.value,
            "write_status": self.write_status.value,
            "queued_at": self.queued_at,
            "completed_at": self.completed_at,
            "reason": self.reason,
            "charger_result": self.charger_result,
        }


class ChargerCommandWaitTimeout(TimeoutError):
    """A caller stopped waiting while the queued command remains active."""

    def __init__(self, command_id: str) -> None:
        super().__init__(f"Command {command_id} is still pending")
        self.command_id = command_id


@dataclass(frozen=True, slots=True)
class ChargerCommandHandle:
    """Await one command without allowing caller cancellation to cancel it."""

    command_id: str
    _completion: asyncio.Future[ChargerCommandResult]

    @property
    def done(self) -> bool:
        """Return whether the queue has published a terminal result."""
        return self._completion.done()

    async def async_wait(
        self,
        *,
        timeout: float,
    ) -> ChargerCommandResult:
        """Wait for completion while keeping the physical command alive."""
        if not isfinite(timeout) or timeout <= 0:
            raise ValueError("Command wait timeout must be finite and positive")
        try:
            # ``shield`` is essential: a timed-out/cancelled HA service call
            # must not cancel the Future that the queue still has to resolve.
            return await asyncio.wait_for(
                asyncio.shield(self._completion),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise ChargerCommandWaitTimeout(self.command_id) from None


def create_command_handle() -> ChargerCommandHandle:
    """Create a globally unique ID and completion Future on the running loop."""
    return ChargerCommandHandle(
        command_id=uuid4().hex,
        _completion=asyncio.get_running_loop().create_future(),
    )


class ChargerConnectionUnavailable(RuntimeError):
    """The selected connection became stale before a request was sent."""


class ChargerRequestOutcomeUncertain(RuntimeError):
    """The connection was lost after handing a request to the OCPP layer."""


def _stringify(value: object) -> str | None:
    """Use enum values in diagnostics while still supporting plain strings."""
    if value is None:
        return None
    return str(value.value if hasattr(value, "value") else value)
