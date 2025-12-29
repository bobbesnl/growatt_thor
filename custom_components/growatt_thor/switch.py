"""Switch entities for Growatt THOR load balancing."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

from ocpp.v16.enums import ConfigurationStatus

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Growatt THOR load balancing switch."""
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities([
        LoadBalancingEnableSwitch(coordinator, entry),
    ])


class LoadBalancingEnableSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to enable/disable load balancing."""

    _attr_has_entity_name = True
    _attr_name = "Loadbalancing enable"
    _attr_icon = "mdi:power-plug-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_load_balancing_enable"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id, "grid_connection")},
            "name": "Growatt THOR Load balancing",  # ← GEWENST
            "manufacturer": "Growatt",
            "model": "THOR Grid Connection",
        }
        self.hass = coordinator.hass

    @property
    def is_on(self):
        """Return true if load balancing is enabled."""
        return self.coordinator.external_limit_power_enable

    async def async_turn_on(self, **kwargs):
        """Enable load balancing."""
        await self._set_value("1")

    async def async_turn_off(self, **kwargs):
        """Disable load balancing."""
        await self._set_value("0")

    async def _set_value(self, value: str):
        """Update the configuration on the charger."""
        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")

        if not charge_point:
            _LOGGER.warning("Cannot change Loadbalancing enable: charger not connected")
            return

        try:
            _LOGGER.info("Setting G_ExternalLimitPowerEnable to %s", value)

            result = await charge_point.change_configuration(
                "G_ExternalLimitPowerEnable",
                value
            )

            new_state = (value == "1")

            if result == ConfigurationStatus.accepted:
                self.coordinator.external_limit_power_enable = new_state
                self.coordinator.async_set_updated_data(True)
                _LOGGER.info("✅ Loadbalancing enable → %s (immediate UI update)",
                           "ON" if new_state else "OFF")
            elif result == ConfigurationStatus.reboot_required:
                _LOGGER.warning("⚠️ Loadbalancing enable → %s (reboot required)",
                              "ON" if new_state else "OFF")
                self.coordinator.external_limit_power_enable = new_state
                self.coordinator.async_set_updated_data(True)
            else:
                _LOGGER.error("❌ Loadbalancing enable change rejected: %s", result)

        except Exception as exc:
            _LOGGER.error("❌ Failed to set Loadbalancing enable: %s", exc, exc_info=True)

