"""Number entities for Growatt THOR configuration."""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.const import UnitOfPower, UnitOfElectricCurrent

from ocpp.v16.enums import ConfigurationStatus

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Growatt THOR number entities."""
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities([
        MaxCurrentNumber(coordinator, entry),
        ExternalLimitPowerNumber(coordinator, entry),
    ])


# ─────────────────────────────
# Base class
# ─────────────────────────────

class BaseConfigNumber(CoordinatorEntity, NumberEntity):
    """Base class for Growatt THOR configuration numbers."""
    
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

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

    async def async_set_native_value(self, value: float) -> None:
        """Update the configuration on the charger."""
        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        
        if not charge_point:
            _LOGGER.warning("Cannot change %s: charger not connected", self.name)
            return

        try:
            # Format value according to key requirements
            formatted_value = self._format_value(value)
            
            _LOGGER.info("Setting %s to %s", self._config_key, formatted_value)
            
            result = await charge_point.change_configuration(
                self._config_key,
                formatted_value
            )

            if result == ConfigurationStatus.accepted:
                _LOGGER.info("%s successfully changed to %s", self.name, formatted_value)
            elif result == ConfigurationStatus.reboot_required:
                _LOGGER.warning("%s changed but charger reboot required", self.name)
            else:
                _LOGGER.error("%s change rejected: %s", self.name, result)

        except Exception as exc:
            _LOGGER.error("Failed to set %s: %s", self.name, exc, exc_info=True)

    def _format_value(self, value: float) -> str:
        """Format value for OCPP (override in subclass if needed)."""
        return str(value)


# ─────────────────────────────
# Max Current (per fase)
# ─────────────────────────────

class MaxCurrentNumber(BaseConfigNumber):
    """Max current per phase configuration."""
    
    _attr_name = "Max Current"
    _attr_icon = "mdi:current-ac"
    _attr_native_min_value = 6
    _attr_native_max_value = 32
    _attr_native_step = 1
    _config_key = "G_MaxCurrent"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "max_current")

    @property
    def native_unit_of_measurement(self):
        return UnitOfElectricCurrent.AMPERE

    @property
    def native_value(self):
        return self.coordinator.max_current

    def _format_value(self, value: float) -> str:
        """Format as XX.00 (Growatt format)."""
        return f"{value:.2f}"


# ─────────────────────────────
# External Limit Power
# ─────────────────────────────

class ExternalLimitPowerNumber(BaseConfigNumber):
    """External limit power (load balancing) configuration."""
    
    _attr_name = "External Limit Power"
    _attr_icon = "mdi:transmission-tower-export"
    _attr_native_min_value = 0
    _attr_native_max_value = 25000  # 25kW max
    _attr_native_step = 100
    _config_key = "G_ExternalLimitPower"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "external_limit_power")

    @property
    def native_unit_of_measurement(self):
        return UnitOfPower.WATT

    @property
    def native_value(self):
        return self.coordinator.external_limit_power

    def _format_value(self, value: float) -> str:
        """Format as integer string."""
        return str(int(value))

