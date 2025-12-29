"""Switch entities for Growatt THOR configuration."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

from ocpp.v16.enums import ConfigurationStatus

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Growatt THOR switch entities."""
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities([
        ExternalLimitPowerEnableSwitch(coordinator, entry),
    ])


# ─────────────────────────────
# External Limit Power Enable
# ─────────────────────────────

class ExternalLimitPowerEnableSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to enable/disable external limit power (load balancing)."""
    
    _attr_has_entity_name = True
    _attr_name = "External Limit Power Enable"
    _attr_icon = "mdi:power-plug-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_external_limit_power_enable"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }
        self.hass = coordinator.hass

    @property
    def is_on(self):
        """Return true if load balancing is enabled."""
        return self.coordinator.external_limit_power_enable

    async def async_turn_on(self, **kwargs):
        """Enable external limit power."""
        await self._set_value("1")

    async def async_turn_off(self, **kwargs):
        """Disable external limit power."""
        await self._set_value("0")

    async def _set_value(self, value: str):
        """Update the configuration on the charger."""
        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        
        if not charge_point:
            _LOGGER.warning("Cannot change External Limit Power Enable: charger not connected")
            return

        try:
            _LOGGER.info("Setting G_ExternalLimitPowerEnable to %s", value)
            
            result = await charge_point.change_configuration(
                "G_ExternalLimitPowerEnable",
                value
            )

            if result == ConfigurationStatus.accepted:
                _LOGGER.info("External Limit Power Enable successfully changed to %s", value)
            elif result == ConfigurationStatus.reboot_required:
                _LOGGER.warning("External Limit Power Enable changed but charger reboot required")
            else:
                _LOGGER.error("External Limit Power Enable change rejected: %s", result)

        except Exception as exc:
            _LOGGER.error("Failed to set External Limit Power Enable: %s", exc, exc_info=True)

