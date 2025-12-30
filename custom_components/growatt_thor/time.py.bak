"""Time entities for Growatt THOR configuration."""
from __future__ import annotations

import logging
from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

from ocpp.v16.enums import ConfigurationStatus

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Growatt THOR time entities."""
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities([
        AutoChargeStartTime(coordinator, entry),
        AutoChargeStopTime(coordinator, entry),
    ])


# ─────────────────────────────
# Base class
# ─────────────────────────────

class BaseAutoChargeTime(CoordinatorEntity, TimeEntity):
    """Base class for auto charge time entities."""
    
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator, entry, key):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }
        self.hass = coordinator.hass

    async def async_set_value(self, value: time) -> None:
        """Update the time configuration on the charger."""
        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        
        if not charge_point:
            _LOGGER.warning("Cannot change %s: charger not connected", self.name)
            return

        # Get current start/stop times
        start_time = self.coordinator.auto_charge_start_time
        stop_time = self.coordinator.auto_charge_stop_time

        # Update the appropriate time
        if self._is_start:
            start_time = value
        else:
            stop_time = value

        # Check if we have both times
        if start_time is None or stop_time is None:
            _LOGGER.warning("Cannot update %s: both start and stop times must be set", self.name)
            return

        # Format as "HH:MM-HH:MM"
        formatted_value = f"{start_time.strftime('%H:%M')}-{stop_time.strftime('%H:%M')}"

        try:
            _LOGGER.info("Setting G_AutoChargeTime to %s", formatted_value)
            
            result = await charge_point.change_configuration(
                "G_AutoChargeTime",
                formatted_value
            )

            if result == ConfigurationStatus.accepted:
                _LOGGER.info("Auto Charge Time successfully changed to %s", formatted_value)
            elif result == ConfigurationStatus.reboot_required:
                _LOGGER.warning("Auto Charge Time changed but charger reboot required")
            else:
                _LOGGER.error("Auto Charge Time change rejected: %s", result)

        except Exception as exc:
            _LOGGER.error("Failed to set Auto Charge Time: %s", exc, exc_info=True)


# ─────────────────────────────
# Auto Charge Start Time
# ─────────────────────────────

class AutoChargeStartTime(BaseAutoChargeTime):
    """Auto charge start time configuration."""
    
    _attr_name = "Auto Charge Start Time"
    _is_start = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "auto_charge_start_time")

    @property
    def native_value(self):
        """Return the current start time."""
        return self.coordinator.auto_charge_start_time


# ─────────────────────────────
# Auto Charge Stop Time
# ─────────────────────────────

class AutoChargeStopTime(BaseAutoChargeTime):
    """Auto charge stop time configuration."""
    
    _attr_name = "Auto Charge Stop Time"
    _is_start = False

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "auto_charge_stop_time")

    @property
    def native_value(self):
        """Return the current stop time."""
        return self.coordinator.auto_charge_stop_time

