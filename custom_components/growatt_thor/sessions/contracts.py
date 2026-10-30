"""Capabilities needed by session clocks and lifecycle processing."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import TYPE_CHECKING, Any, Protocol

from ..energy.contracts import SiteObservationOwner

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..charging.authorization import LocalAuthorization
    from ..configuration.values import ConfigurationValue
    from ..energy.session_accumulator import SessionAccumulator
    from .duration import EffectiveChargingTracker
    from .hooks import TransactionHooks


class SessionClock(Protocol):
    hass: HomeAssistant
    configuration_values: Mapping[str, ConfigurationValue]


class TelemetryOwner(SiteObservationOwner, SessionClock, Protocol):
    last_meter_values: dict[str, Any] | None
    status: str | None

    def effective_meter_gap_seconds(self) -> float: ...


class SessionOwner(TelemetryOwner, Protocol):
    """Shared charger observations and persistence; lifecycle state stays local."""

    active_transaction: dict[str, Any] | None
    authorization: LocalAuthorization
    charge_point_id: str | None
    connected: bool
    currents: dict[str, float]
    effective_charging: EffectiveChargingTracker
    energy: float | None
    id_tag: str | None
    last_completed_transaction: dict[str, Any] | None
    last_current_record: dict[str, Any] | None
    last_energy_stop: dict[str, Any] | None
    last_frozen_record: dict[str, Any] | None
    last_meter_values: dict[str, Any] | None
    last_site_accounting: SessionAccumulator | None
    location: str
    phase_power: dict[str, float]
    power: float | None
    runtime_data: MutableMapping[str, Any]
    site_accounting: SessionAccumulator | None
    site_accounting_options: dict[str, Any]
    site_accounting_totals: dict[str, float]
    source_instance_id: str | None
    status: str | None
    total_energy_charged: float
    transaction_hooks: TransactionHooks | None
    transaction_id: int | None
    voltages: dict[str, float]

    async def async_save_storage(self) -> None: ...

    def async_set_updated_data(self, data: bool) -> None: ...

    def effective_meter_gap_seconds(self) -> float: ...

    def now(self) -> str: ...

    def schedule_storage_save(self) -> None: ...
