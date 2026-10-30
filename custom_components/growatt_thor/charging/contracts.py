"""Capabilities used by guarded Start/Stop commands."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..runtime.write_results import ChargerCommandHandle


class CommandOwner(Protocol):
    hass: HomeAssistant
    connected: bool
    dashboard_command: dict[str, Any]
    runtime_data: MutableMapping[str, Any]
    status: str | None
    transaction_id: int | None
    charging_target_request: dict[str, Any] | None

    @property
    def charger_is_faulted(self) -> bool: ...

    @property
    def transaction_is_active(self) -> bool: ...

    def now(self) -> str: ...

    def async_set_updated_data(self, data: bool) -> None: ...

    def cancel_queued_writes(self, **kwargs: Any) -> int: ...

    async def queue_write(self, *args: Any, **kwargs: Any) -> ChargerCommandHandle: ...

    def record_stop_requested(self, *, reason: str = "remote_stop") -> None: ...
