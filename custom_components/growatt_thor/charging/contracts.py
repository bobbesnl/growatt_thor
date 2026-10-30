"""Capabilities used by guarded Start/Stop commands."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..configuration.writes import ConfigurationWriteStatus
    from ..runtime.write_results import ChargerCommandHandle
    from .pv_linkage import PvLinkageApplyResult, PvLinkageDraft


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


class PvApplyOwner(Protocol):
    """Write tracking and draft reconciliation for one compound PV Apply."""

    def begin_configuration_write(self, key: str, raw_value: str) -> int: ...

    def acknowledge_configuration_write(
        self, key: str, *, generation: int, accepted: bool, result: object
    ) -> bool: ...

    def update_configuration_value(self, key: str, raw_value: str) -> None: ...

    def mark_configuration_write(
        self,
        key: str,
        status: ConfigurationWriteStatus,
        *,
        generation: int,
        result: str | None = None,
    ) -> bool: ...

    def record_pv_linkage_apply_result(self, result: PvLinkageApplyResult) -> None: ...

    def schedule_configuration_refresh(self, *, delay: float = 20.0) -> object: ...

    def mark_pv_linkage_draft_applied(self, expected_draft: PvLinkageDraft) -> bool: ...


class PvApplyTransport(Protocol):
    async def change_configuration(self, key: str, value: str) -> object: ...

    async def send_data_transfer(self, *, vendor_id: str, message_id: str, data: str) -> object: ...
