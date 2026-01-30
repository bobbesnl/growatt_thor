"""Number entities for Growatt THOR load balancing."""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberDeviceClass, NumberMode
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

from ocpp.v16.enums import ConfigurationStatus

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Growatt THOR number entities."""
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities([
        MaxCurrentNumber(coordinator, entry),
        LoadBalancingLimitNumber(coordinator, entry),
    ])


# ─────────────────────────────
# Base class
# ─────────────────────────────

class BaseConfigNumber(CoordinatorEntity, NumberEntity):
    """Base class for Growatt THOR configuration numbers."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_mode = NumberMode.BOX

    def __init__(self, coordinator, entry, key):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self.hass = coordinator.hass

    def _format_value(self, value: float) -> str:
        """Format value for OCPP (override in subclass if needed)."""
        return str(int(round(value)))


# ─────────────────────────────
# Max Current
# ─────────────────────────────

class MaxCurrentNumber(BaseConfigNumber):
    """Max current per phase configuration."""

    _attr_name = "Max Current"
    _attr_icon = "mdi:current-ac"
    _attr_native_min_value = 6
    _attr_native_max_value = 32
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "A"
    _config_key = "G_MaxCurrent"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "max_current")
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }

    @property
    def native_value(self):
        value = self.coordinator.max_current
        return int(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """Set new value via queue (directe update UI)."""
        value = int(round(value))

        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if not charge_point:
            _LOGGER.warning("Cannot change Max Current: charger not connected")
            return

        # Optimistic UI update
        self.coordinator.max_current = value
        self.coordinator.async_set_updated_data(True)
        _LOGGER.info("📝 Max Current UI updated to %d A (queued for write)", value)

        await self.coordinator.queue_write(
            self._write_to_thor,
            charge_point,
            value,
            dedupe_key=self._config_key,  # ✅ only keep latest G_MaxCurrent in queue
        )

    async def _write_to_thor(self, charge_point, value: int):
        """Daadwerkelijke write naar Thor."""
        try:
            formatted_value = str(value)

            result = await charge_point.change_configuration(
                self._config_key,
                formatted_value
            )

            if result == ConfigurationStatus.accepted:
                _LOGGER.info("✅ Max Current written to Thor: %s A", formatted_value)
            elif result == ConfigurationStatus.reboot_required:
                _LOGGER.warning("⚠️ Max Current write accepted (reboot required): %s A", formatted_value)
            else:
                _LOGGER.error("❌ Max Current rejected by Thor: %s", result)

        except Exception as exc:
            _LOGGER.error("❌ Failed to set Max Current: %s", exc, exc_info=True)


# ─────────────────────────────
# Load Balancing Limit
# ─────────────────────────────

class LoadBalancingLimitNumber(BaseConfigNumber):
    """Load balancing limit (kW) configuration."""

    _attr_name = "Loadbalancing limit"
    _attr_icon = "mdi:speedometer"
    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_min_value = 1
    _attr_native_max_value = 50
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "kW"
    _config_key = "G_ExternalLimitPower"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "load_balancing_limit")
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id, "grid_connection")},
            "name": "Growatt THOR Load balancing",
            "manufacturer": "Growatt",
            "model": "THOR Load balancing",
        }

    @property
    def native_value(self):
        value = self.coordinator.external_limit_power
        return int(value) if value is not None else 10

    async def async_set_native_value(self, value: float) -> None:
        """Set new value via queue (directe update UI)."""
        value = int(round(value))

        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if not charge_point:
            _LOGGER.warning("Cannot change Load Balancing Limit: charger not connected")
            return

        # Optimistic UI update
        self.coordinator.external_limit_power = value
        self.coordinator.async_set_updated_data(True)
        _LOGGER.info("📝 Load Balancing Limit UI updated to %d kW (queued for write)", value)

        await self.coordinator.queue_write(
            self._write_to_thor,
            charge_point,
            value,
            dedupe_key=self._config_key,  # ✅ only keep latest G_ExternalLimitPower in queue
        )

    async def _write_to_thor(self, charge_point, value: int):
        """Daadwerkelijke write naar Thor."""
        try:
            formatted_value = str(value)

            result = await charge_point.change_configuration(
                self._config_key,
                formatted_value
            )

            if result == ConfigurationStatus.accepted:
                _LOGGER.info("✅ Load Balancing Limit written to Thor: %s kW", formatted_value)
            elif result == ConfigurationStatus.reboot_required:
                _LOGGER.warning("⚠️ Load Balancing Limit write accepted (reboot required): %s kW", formatted_value)
            else:
                _LOGGER.error("❌ Load Balancing Limit rejected by Thor: %s", result)

        except Exception as exc:
            _LOGGER.error("❌ Failed to set Load Balancing Limit: %s", exc, exc_info=True)
