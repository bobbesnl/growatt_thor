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


class ChargerWriteStatus(str, Enum):
    """Result of one logical command submitted to the charger write queue."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    UNCERTAIN = "uncertain"


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


class ChargerConnectionUnavailable(RuntimeError):
    """The selected connection became stale before a request was sent."""


class ChargerRequestOutcomeUncertain(RuntimeError):
    """The connection was lost after handing a request to the OCPP layer."""


def _stringify(value: object) -> str | None:
    """Use enum values in diagnostics while still supporting plain strings."""
    if value is None:
        return None
    return str(value.value if hasattr(value, "value") else value)
