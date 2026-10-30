"""Single-attempt pilot sequence; all dependencies are injectable for testing."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from .model import ChargingTarget, TargetState


async def run_target_sequence(
    target: ChargingTarget,
    *,
    check: Callable[[], str | None],
    save: Callable[[str], Awaitable[None]],
    send_target: Callable[[ChargingTarget], Awaitable[str]],
    start: Callable[[], Awaitable[str]] | None,
    pause_seconds: float,
    waiting_state: str = TargetState.TARGET_ACCEPTED_WAITING_FOR_RFID,
    sleep=asyncio.sleep,
) -> None:
    """Never start after a failed/uncertain target write, and never retry.

    Persist intent BEFORE sending. A crash or transport failure cannot leave a
    clean local state suggesting that the charger definitely has no target.
    The caller holds the shared firmware write queue for the complete sequence.
    """
    try:
        if check():
            await save(TargetState.BLOCKED_BEFORE_TARGET)
            return
        await save(TargetState.SENDING_TARGET)
        status = await send_target(target)
        if status != "Accepted":
            await save(TargetState.TARGET_REJECTED)
            return
        await save(TargetState.TARGET_ACCEPTED)
        if start is None:
            await save(waiting_state)
            return
        await sleep(pause_seconds)
        if check():
            await save(TargetState.TARGET_ACCEPTED_START_BLOCKED)
            return
        await save(TargetState.SENDING_START)
        status = await start()
        await save(
            TargetState.START_ACCEPTED
            if status == "Accepted"
            else TargetState.START_REJECTED_TARGET_MAY_REMAIN
        )
    except asyncio.CancelledError:
        # Last persisted sending/accepted state already requires reconciliation.
        raise
    except Exception:  # noqa: BLE001 - retain uncertainty without logging wire payloads
        # OCPP exceptions can contain raw idTags; never log the exception payload.
        await save(TargetState.OUTCOME_UNKNOWN)


async def run_reservation_sequence(
    target: ChargingTarget,
    *,
    check: Callable[[], str | None],
    save: Callable[[str], Awaitable[None]],
    send_target: Callable[[ChargingTarget], Awaitable[str]],
    reserve: Callable[[], Awaitable[str]],
    pause_seconds: float = 1,
    sleep=asyncio.sleep,
) -> None:
    """Set a target and create exactly one charger-side reservation.

    The reservation identifier is persisted by the caller before this function
    runs. Unknown outcomes are never retried automatically.
    """
    try:
        if check():
            await save(TargetState.BLOCKED_BEFORE_TARGET)
            return
        await save(TargetState.SENDING_TARGET)
        if await send_target(target) != "Accepted":
            await save(TargetState.TARGET_REJECTED)
            return
        await save(TargetState.TARGET_ACCEPTED)
        await sleep(pause_seconds)
        if check():
            await save(TargetState.TARGET_ACCEPTED_RESERVATION_BLOCKED)
            return
        await save(TargetState.SENDING_RESERVATION)
        status = await reserve()
        await save(
            TargetState.SCHEDULED
            if status == "Accepted"
            else TargetState.RESERVATION_REJECTED_TARGET_MAY_REMAIN
        )
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - OCPP errors may contain private payloads
        await save(TargetState.OUTCOME_UNKNOWN)
