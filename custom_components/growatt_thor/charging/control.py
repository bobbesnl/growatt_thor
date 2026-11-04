"""What callers may ask of a charger, split into capabilities.

Like evcc's charger API, the base protocol covers what every supported charger
does, and optional capabilities are separate protocols. Implementations add no
rules of their own: every outbound write still runs inside a write-queue
callback, and revalidation stays with the commands that own it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ..ocpp.growatt.server import GrowattChargePoint
    from ..runtime.write_results import ChargerCommandResult
    from ..targets.requests import TargetRecord


class ChargerControl(Protocol):
    """Start and Stop through the charger's single write owner."""

    @property
    def start_block_reason(self) -> str | None:
        """Why a Start would be refused now, or None when it may be queued."""
        ...

    async def async_start(self) -> None:
        """Queue a Start and wait for its bounded outcome."""
        ...

    async def async_stop(
        self,
        *,
        auto_guard: Callable[[], str | None] | None = None,
        stop_reason: str | None = None,
        on_result: Callable[[ChargerCommandResult], None] | None = None,
    ) -> None:
        """Queue a Stop for the observed transaction and wait for its outcome.

        ``auto_guard`` is rechecked immediately before the Stop is sent;
        ``on_result`` receives the terminal queue result.
        """
        ...


class NativeTargetControl(Protocol):
    """Optional capability: wallbox-native targets, reservations and remote start.

    These calls run inside the target runtime's queue callbacks, bound to the
    charge point that the operation check accepted.
    """

    def active_charge_point(self) -> GrowattChargePoint | None: ...

    def block_reason(self, cp: GrowattChargePoint | None, activation: str) -> str | None: ...

    async def remote_start(self, cp: GrowattChargePoint) -> str: ...

    async def reserve(self, cp: GrowattChargePoint, request: TargetRecord) -> str: ...

    async def cancel_reservation(self, cp: GrowattChargePoint, reservation_id: int) -> str: ...
