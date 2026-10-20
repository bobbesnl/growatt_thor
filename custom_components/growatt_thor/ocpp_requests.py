"""Serialize OCPP requests initiated by Home Assistant.

The OCPP library protects individual CALL frames, but the Growatt THOR also
needs protection at the level of a *logical operation*.  For example, our
GetConfiguration refresh consists of two CALLs and must not be interleaved
with a queued ChangeConfiguration.  Keeping that policy in this small class
makes the firmware workaround explicit and independently testable.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from .write_queue import (
    ChargerConnectionUnavailable,
    ChargerRequestOutcomeUncertain,
)


ResultT = TypeVar("ResultT")

# A private sentinel is preferable to ``None`` because valid OCPP helpers may
# themselves return no payload.  Callers can therefore distinguish "skipped
# on purpose" from "request completed without data".
class _RequestSkipped:
    """Marker type used only for identity checks by request callers."""


REQUEST_SKIPPED = _RequestSkipped()


class SerializedOcppRequestGate:
    """Run at most one integration-initiated OCPP operation at a time."""

    def __init__(
        self,
        *,
        connection_is_current: Callable[[], bool],
        connection_is_available: Callable[[], bool],
        writes_are_pending: Callable[[], bool],
        uncertain_transport_errors: tuple[type[BaseException], ...],
    ) -> None:
        self._connection_is_current = connection_is_current
        self._connection_is_available = connection_is_available
        self._writes_are_pending = writes_are_pending
        self._uncertain_transport_errors = uncertain_transport_errors
        self._lock = asyncio.Lock()

    async def run(
        self,
        operation_name: str,
        operation: Callable[[], Awaitable[ResultT]],
        *,
        skip_if_writes_pending: bool = False,
        timeout_makes_outcome_uncertain: bool = False,
    ) -> ResultT | _RequestSkipped:
        """Run one logical operation after rechecking connection and priority.

        Optional reads check ``writes_are_pending`` twice.  The second check is
        intentionally inside the lock: a read may have waited behind another
        request while a user write entered the queue.  In that case the write
        keeps priority and the caller can retry the read later.

        A stale connection is detected before ``operation`` starts and is safe
        to retry.  Transport loss after the hand-off is different: the frame
        may already have reached the THOR, so the result must be reconciled by
        readback instead of blindly sending the command again.
        """
        if skip_if_writes_pending and self._writes_are_pending():
            return REQUEST_SKIPPED

        async with self._lock:
            if (
                not self._connection_is_current()
                or not self._connection_is_available()
            ):
                raise ChargerConnectionUnavailable(
                    f"{operation_name}: charger connection is no longer current"
                )
            if skip_if_writes_pending and self._writes_are_pending():
                return REQUEST_SKIPPED

            try:
                result = await operation()
                if not self._connection_is_current():
                    # The request was handed to OCPP and may even have a valid
                    # response, but a reconnect changed the owner while it was
                    # in flight.  Never retry it blindly and never let the old
                    # socket's result update state owned by the new socket.
                    raise ChargerRequestOutcomeUncertain(
                        f"{operation_name}: connection was superseded while "
                        "the request was in flight"
                    )
                return result
            except ChargerRequestOutcomeUncertain:
                raise
            except self._uncertain_transport_errors as exc:
                raise ChargerRequestOutcomeUncertain(
                    f"{operation_name}: connection lost before acknowledgement"
                ) from exc
            except asyncio.TimeoutError as exc:
                if not timeout_makes_outcome_uncertain:
                    raise
                # A timeout only says that no acknowledgement arrived.  It
                # cannot prove whether the charger applied a write before the
                # response was lost.
                raise ChargerRequestOutcomeUncertain(
                    f"{operation_name}: no acknowledgement before timeout"
                ) from exc
