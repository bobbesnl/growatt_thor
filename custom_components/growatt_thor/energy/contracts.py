"""Shared read capabilities for site telemetry and accounting inputs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from ..charging.contracts import CommandOwner

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..configuration.values import ConfigurationValue
    from ..ocpp.external_meter_state import ExternalMeterState


class SiteObservationOwner(Protocol):
    hass: HomeAssistant
    site_accounting_options: dict[str, Any]
    battery_power_entity: str | None
    battery_power_sign: str
    external_meter: ExternalMeterState


class LiveAllocationOwner(SiteObservationOwner, Protocol):
    source_instance_id: str | None
    charge_point_id: str | None
    transaction_id: int | str | None

    @property
    def transaction_is_active(self) -> bool: ...

    def now(self) -> str: ...

    @property
    def effective_meter_gap_seconds(self) -> float: ...


class EnergyStopOwner(CommandOwner, LiveAllocationOwner, Protocol):
    configuration_values: dict[str, ConfigurationValue]
    last_meter_values: dict[str, Any] | None
    last_energy_stop: dict[str, object] | None

    def schedule_storage_save(self) -> None: ...
