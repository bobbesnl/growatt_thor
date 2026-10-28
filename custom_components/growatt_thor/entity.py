"""Shared Home Assistant entity identity and device metadata."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.helpers.device_registry import DeviceInfo

    from .coordinator import GrowattCoordinator

INFORMATION_ATTRIBUTES = {"information": "details"}


def charger_device_info(entry: ConfigEntry) -> DeviceInfo:
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": "Growatt THOR EV Charger",
        "manufacturer": "Growatt",
        "model": "THOR",
    }


def meter_device_info(entry: ConfigEntry) -> DeviceInfo:
    return {
        "identifiers": {(DOMAIN, entry.entry_id, "grid_connection")},
        "name": "Growatt THOR External Meter",
        "manufacturer": "Growatt",
        "model": "THOR External Meter",
    }


class ThorEntity(CoordinatorEntity):
    """Attach one entity to its entry's charger or external meter device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GrowattCoordinator,
        entry: ConfigEntry,
        *,
        device: Literal["charger", "meter"] = "charger",
    ) -> None:
        super().__init__(coordinator)
        self._attr_device_info = (
            meter_device_info(entry) if device == "meter" else charger_device_info(entry)
        )

    @property
    def information_attributes(self) -> dict[str, str]:
        """Give each caller its own metadata mapping, as before."""
        return dict(INFORMATION_ATTRIBUTES)
