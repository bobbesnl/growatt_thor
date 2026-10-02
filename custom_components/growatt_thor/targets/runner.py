"""Single-attempt pilot sequence; all dependencies are injectable for testing."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from .model import ChargingTarget


async def run_target_sequence(
    target: ChargingTarget,
    *,
    check: Callable[[], str | None],
    save: Callable[[str], Awaitable[None]],
    send_target: Callable[[ChargingTarget], Awaitable[str]],
    start: Callable[[], Awaitable[str]] | None,
    pause_seconds: float,
    waiting_state: str = "target_accepted_waiting_for_rfid",
    sleep=asyncio.sleep,
) -> None:
    """Never start after a failed/uncertain target write, and never retry.

    Persist intent BEFORE sending. A crash or transport failure cannot leave a
    clean local state suggesting that the charger definitely has no target.
    The caller holds the shared firmware write queue for the complete sequence.
    """
    try:
        if check():
            await save("blocked_before_target")
            return
        await save("sending_target")
        status = await send_target(target)
        if status != "Accepted":
            await save("target_rejected")
            return
        await save("target_accepted")
        if start is None:
            await save(waiting_state)
            return
        await sleep(pause_seconds)
        if check():
            await save("target_accepted_start_blocked")
            return
        await save("sending_start")
        status = await start()
        await save(
            "start_accepted"
            if status == "Accepted"
            else "start_rejected_target_may_remain"
        )
    except asyncio.CancelledError:
        # Last persisted sending/accepted state already requires reconciliation.
        raise
    except Exception:  # noqa: BLE001 - retain uncertainty without logging wire payloads
        # OCPP exceptions can contain raw idTags; never log the exception payload.
        await save("outcome_unknown")


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
            await save("blocked_before_target")
            return
        await save("sending_target")
        if await send_target(target) != "Accepted":
            await save("target_rejected")
            return
        await save("target_accepted")
        await sleep(pause_seconds)
        if check():
            await save("target_accepted_reservation_blocked")
            return
        await save("sending_reservation")
        status = await reserve()
        await save(
            "scheduled"
            if status == "Accepted"
            else "reservation_rejected_target_may_remain"
        )
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - OCPP errors may contain private payloads
        await save("outcome_unknown")
