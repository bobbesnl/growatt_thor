"""Select entities for verified Growatt THOR charging controls."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from ocpp.v16.enums import ConfigurationStatus

from .charging_controls import (
    encode_working_mode,
    selected_working_mode,
)
from .const import DOMAIN


_LOGGER = logging.getLogger(__name__)
WORKING_MODE_OPTIONS = ["fast", "pv_linkage", "pv_linkage_plus", "off_peak"]


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Growatt THOR select entities."""
    coordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities([WorkingModeSelect(coordinator, entry)])


class WorkingModeSelect(CoordinatorEntity, SelectEntity):
    """Select a charging strategy through the captured indirect writes."""

    _attr_has_entity_name = True
    _attr_translation_key = "working_mode"
    _attr_icon = "mdi:ev-station"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = WORKING_MODE_OPTIONS

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self.hass = coordinator.hass
        self._attr_unique_id = f"{entry.entry_id}_working_mode_control"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }

    @property
    def current_option(self):
        return selected_working_mode(self.coordinator.configuration_values)

    @property
    def available(self):
        return (
            super().available
            and self.coordinator.connected
            and self.current_option is not None
        )

    @property
    def extra_state_attributes(self):
        return {"information": "details"}

    async def async_select_option(self, option: str) -> None:
        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if charge_point is None:
            _LOGGER.warning("Cannot change working mode: charger not connected")
            return
        key, raw_value = encode_working_mode(option)
        await self.coordinator.queue_write(
            self._apply_working_mode,
            charge_point,
            key,
            raw_value,
            option,
            dedupe_key="working_mode",
        )

    async def _apply_working_mode(
        self,
        charge_point,
        key: str,
        raw_value: str,
        option: str,
    ) -> None:
        result = await charge_point.change_configuration(key, raw_value)
        if result not in {
            ConfigurationStatus.accepted,
            ConfigurationStatus.reboot_required,
        }:
            _LOGGER.error("Working mode change rejected by charger: %s", result)
            return

        self.coordinator.update_configuration_value(key, raw_value)
        reported_mode = {
            "fast": "Fast",
            "pv_linkage": "PVlink",
            "pv_linkage_plus": "PVlink",
            "off_peak": "Off Peak",
        }[option]
        self.coordinator.update_configuration_value(
            "G_WorkingMode",
            reported_mode,
        )
        if option == "off_peak":
            self.coordinator.update_configuration_value("G_SolarMode", "1&0")
        elif option in {"fast", "pv_linkage", "pv_linkage_plus"}:
            self.coordinator.update_configuration_value(
                "G_OffPeakEnable",
                "1&Disable",
            )

        self.hass.async_create_task(self._refresh_configuration(charge_point))

    async def _refresh_configuration(self, charge_point) -> None:
        """Confirm the effective mode after the charger has applied the write."""
        await asyncio.sleep(20)
        if self.hass.data.get(DOMAIN, {}).get("charge_point") is charge_point:
            await charge_point.trigger_get_configuration()
