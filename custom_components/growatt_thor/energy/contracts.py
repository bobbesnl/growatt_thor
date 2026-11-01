"""Shared read capabilities for site telemetry and accounting inputs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..ocpp.external_meter_state import ExternalMeterState


class SiteObservationOwner(Protocol):
    hass: HomeAssistant
    site_accounting_options: dict[str, Any]
    battery_power_entity: str | None
    battery_power_sign: str
    external_meter: ExternalMeterState
