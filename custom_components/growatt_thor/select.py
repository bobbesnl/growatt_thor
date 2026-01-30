"""Select entities for Growatt THOR configuration."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

from ocpp.v16.enums import ConfigurationStatus

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Growatt THOR select entities."""
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities([
        ChargerModeSelect(coordinator, entry),
    ])


class ChargerModeSelect(CoordinatorEntity, SelectEntity):
    """Select entity for charger mode."""

    _attr_has_entity_name = True
    _attr_name = "Charger Mode"
    _attr_icon = "mdi:ev-station"
    _attr_entity_category = EntityCategory.CONFIG

    # Mapping: internal value → display name
    _MODE_MAP = {
        "1": "HA/RFID",
        "2": "RFID Only",
        "3": "Plug & Charge",
    }

    # Reverse mapping voor select
    _REVERSE_MAP = {v: k for k, v in _MODE_MAP.items()}

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_charger_mode"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }
        self.hass = coordinator.hass

    @property
    def options(self):
        """Return available options."""
        return list(self._REVERSE_MAP.keys())

    @property
    def current_option(self):
        """Return current mode as display name."""
        if self.coordinator.charger_mode is None:
            return None

        mode_str = str(self.coordinator.charger_mode)
        return self._MODE_MAP.get(mode_str)

    async def async_select_option(self, option: str):
        """Change the charger mode (via write queue)."""
        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if not charge_point:
            _LOGGER.warning("Cannot change Charger Mode: charger not connected")
            return

        # Convert display name → internal value
        value = self._REVERSE_MAP.get(option)
        if not value:
            _LOGGER.error("Invalid charger mode option: %s", option)
            return

        try:
            await self.coordinator.queue_write(
                self._apply_charger_mode,
                charge_point,
                value,
                option
            )
        except Exception as exc:
            _LOGGER.error("Failed to queue Charger Mode change: %s", exc, exc_info=True)

    async def _apply_charger_mode(self, charge_point, value: str, option: str):
        """Actually write charger mode to the charger (runs inside write-queue)."""
        try:
            _LOGGER.info("Setting G_ChargerMode to %s (%s)", value, option)

            result = await charge_point.change_configuration(
                "G_ChargerMode",
                value
            )

            if result == ConfigurationStatus.accepted:
                self.coordinator.charger_mode = int(value)
                self.coordinator.async_set_updated_data(True)
                _LOGGER.info("✅ Charger Mode successfully changed to %s", option)
            elif result == ConfigurationStatus.reboot_required:
                self.coordinator.charger_mode = int(value)
                self.coordinator.async_set_updated_data(True)
                _LOGGER.warning("⚠️ Charger Mode changed to %s (reboot required)", option)
            else:
                _LOGGER.error("❌ Charger Mode change rejected: %s", result)

        except Exception as exc:
            _LOGGER.error("Failed to set Charger Mode: %s", exc, exc_info=True)
