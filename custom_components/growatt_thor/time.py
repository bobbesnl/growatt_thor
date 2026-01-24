"""Time entities for Growatt THOR configuration."""
from __future__ import annotations

import logging
from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

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
# Base class (met auto-apply!)
# ─────────────────────────────

class BaseAutoChargeTime(CoordinatorEntity, TimeEntity):
    """Base class for auto charge time entities (auto-apply via queue)."""

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
        """Update tijd en auto-apply via queue."""
        _LOGGER.info("📝 %s changed to %s (auto-queuing)", self.name, value.strftime('%H:%M'))

        # Update pending value in coordinator
        if self._is_start:
            self.coordinator.auto_charge_start_time_pending = value
        else:
            self.coordinator.auto_charge_stop_time_pending = value

        self.coordinator.async_set_updated_data(True)
        
        # Auto-apply via queue!
        start_time = self.coordinator.auto_charge_start_time_pending
        stop_time = self.coordinator.auto_charge_stop_time_pending
        
        if start_time and stop_time:
            formatted_value = f"{start_time.strftime('%H:%M')}-{stop_time.strftime('%H:%M')}"
            _LOGGER.info("🔄 Auto-queueing schedule update: %s", formatted_value)
            
            await self.coordinator.queue_write(
                self._apply_schedule,
                formatted_value,
                start_time,
                stop_time
            )

    async def _apply_schedule(self, formatted_value, start_time, stop_time):
        """Daadwerkelijke write naar Thor."""
        from ocpp.v16.enums import ConfigurationStatus
        
        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")

        if not charge_point:
            _LOGGER.warning("Cannot apply schedule: charger not connected")
            return

        try:
            result = await charge_point.change_configuration(
                "G_AutoChargeTime",
                formatted_value
            )

            if result == ConfigurationStatus.accepted:
                self.coordinator.auto_charge_start_time = start_time
                self.coordinator.auto_charge_stop_time = stop_time
                self.coordinator.async_set_updated_data(True)
                _LOGGER.info("✅ Auto-applied charging schedule: %s", formatted_value)
            else:
                _LOGGER.error("❌ Charging schedule rejected: %s", result)

        except Exception as exc:
            _LOGGER.error("❌ Failed to auto-apply schedule: %s", exc, exc_info=True)


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
        """Return pending start time."""
        return self.coordinator.auto_charge_start_time_pending

    @property
    def extra_state_attributes(self):
        """Show Thor value vs pending."""
        thor_value = self.coordinator.auto_charge_start_time
        return {
            "thor_value": thor_value.strftime('%H:%M') if thor_value else None,
            "note": "Auto-applies via write queue"
        }


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
        """Return pending stop time."""
        return self.coordinator.auto_charge_stop_time_pending

    @property
    def extra_state_attributes(self):
        """Show Thor value vs pending."""
        thor_value = self.coordinator.auto_charge_stop_time
        return {
            "thor_value": thor_value.strftime('%H:%M') if thor_value else None,
            "note": "Auto-applies via write queue"
        }

