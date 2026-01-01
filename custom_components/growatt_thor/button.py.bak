"""Button entities for Growatt THOR configuration."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

from ocpp.v16.enums import ConfigurationStatus

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Growatt THOR button entities."""
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities([
        ApplyChargingScheduleButton(coordinator, entry),
    ])


# ─────────────────────────────
# Apply Charging Schedule Button
# ─────────────────────────────

class ApplyChargingScheduleButton(CoordinatorEntity, ButtonEntity):
    """Button to write both start/stop times to Thor (atomic update)."""

    _attr_has_entity_name = True
    _attr_name = "Apply charging schedule"
    _attr_icon = "mdi:content-save"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_apply_charging_schedule"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }
        self.hass = coordinator.hass

    async def async_press(self) -> None:
        """Write BOTH start/stop times to Thor as single G_AutoChargeTime."""
        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")

        if not charge_point:
            _LOGGER.warning("Cannot apply schedule: charger not connected")
            return

        # Get pending times
        start_time = self.coordinator.auto_charge_start_time_pending
        stop_time = self.coordinator.auto_charge_stop_time_pending

        if start_time is None or stop_time is None:
            _LOGGER.error("Cannot apply: Both start and stop times must be set")
            return

        # Format as "HH:MM-HH:MM" (Thor format)
        formatted_value = f"{start_time.strftime('%H:%M')}-{stop_time.strftime('%H:%M')}"

        try:
            _LOGGER.info("🔘 Applying charging schedule: %s", formatted_value)

            result = await charge_point.change_configuration(
                "G_AutoChargeTime",
                formatted_value
            )

            if result == ConfigurationStatus.accepted:
                # Update coordinator with confirmed values
                self.coordinator.auto_charge_start_time = start_time
                self.coordinator.auto_charge_stop_time = stop_time
                self.coordinator.async_set_updated_data(True)
                
                _LOGGER.info("✅ Charging schedule applied: %s (Thor will reboot)", formatted_value)
            else:
                _LOGGER.error("❌ Charging schedule rejected: %s", result)

        except Exception as exc:
            _LOGGER.error("❌ Failed to apply charging schedule: %s", exc, exc_info=True)

