"""Read capabilities used by card projections, separate from wire dictionaries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from ..charging.snapshot import ChargerStateOwner
from ..energy.contracts import LiveAllocationOwner
from ..sessions.contracts import SessionClock

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..charging.pv_draft import PvLinkageDraftState
    from ..energy.session_accumulator import SessionAccumulator
    from ..sessions.active_state import ActiveTransaction
    from ..sessions.telemetry import SessionTelemetry


class BatteryOwner(Protocol):
    hass: HomeAssistant
    battery_power_entity: str | None
    battery_power_sign: str


class ActiveSessionView(Protocol):
    active_power_curve: list[list[Any]]

    @property
    def telemetry(self) -> SessionTelemetry | None: ...


class ActiveSessionOwner(SessionClock, Protocol):
    active_transaction: ActiveTransaction | None
    transaction_id: int | str | None
    source_instance_id: str | None
    charge_point_id: str | None
    energy: float | None
    id_tag: str | None
    site_accounting: SessionAccumulator | None

    @property
    def sessions(self) -> ActiveSessionView: ...

    dashboard_sessions: dict[str, Any]

    @property
    def transaction_is_active(self) -> bool: ...


class DashboardOwner(
    ActiveSessionOwner, ChargerStateOwner, LiveAllocationOwner, BatteryOwner, Protocol
):
    boot_notification: dict[str, Any] | None
    last_status_notification: dict[str, Any] | None
    charging_target_pilot_enabled: bool
    charging_target_request: dict[str, Any] | None
    connection_started_at: str | None
    max_current: float | None
    pv_draft: PvLinkageDraftState
    dashboard_command: dict[str, object] | None
    last_energy_stop: dict[str, object] | None

    @property
    def charger_is_faulted(self) -> bool: ...
