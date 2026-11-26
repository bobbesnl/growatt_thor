"""Growatt THOR over OCPP 1.6 as the integration's ChargerControl."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from .commands import StartChargingCommand, StopChargingCommand

if TYPE_CHECKING:
    from ..runtime.write_results import ChargerCommandResult
    from .contracts import CommandOwner


class GrowattOcppCharger:
    """The only ChargerControl implementation.

    Start and Stop keep their revalidation, queue submission and command-state
    reporting in StartChargingCommand and StopChargingCommand. This class only
    selects them, so the write queue stays the single owner of charger writes.
    The commands hold no state besides their owner, so a fresh command per call
    behaves like a retained one.
    """

    __slots__ = ("_owner",)

    def __init__(self, owner: CommandOwner) -> None:
        self._owner = owner

    @property
    def start_block_reason(self) -> str | None:
        return StartChargingCommand(self._owner).write_block_reason

    async def async_start(self) -> None:
        await StartChargingCommand(self._owner).async_request()

    async def async_stop(
        self,
        *,
        auto_guard: Callable[[], str | None] | None = None,
        stop_reason: str | None = None,
        on_result: Callable[[ChargerCommandResult], None] | None = None,
    ) -> None:
        await StopChargingCommand(self._owner).async_request(
            auto_guard=auto_guard, stop_reason=stop_reason, on_result=on_result
        )
