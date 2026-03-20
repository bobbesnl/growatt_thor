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
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities([
        MaxCurrentNumber(coordinator, entry),
        LoadBalancingLimitNumber(coordinator, entry),
    ])


# ─────────────────────────────
# Base class
# ─────────────────────────────

class BaseConfigNumber(CoordinatorEntity, NumberEntity):

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_mode = NumberMode.BOX

    def __init__(self, coordinator, entry, key):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self.hass = coordinator.hass

    def _format_value(self, value: float) -> str:
        return str(int(round(value)))


# ─────────────────────────────
# Max Current
# ─────────────────────────────

class MaxCurrentNumber(BaseConfigNumber):

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
        value = int(round(value))

        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if not charge_point:
            _LOGGER.warning("Cannot change Max Current: charger not connected")
            return

        current = self.coordinator.max_current
        if current is not None and int(round(current)) == value:
            _LOGGER.debug("Max Current unchanged (%d A) - skipping write", value)
            return

        previous = int(round(current)) if current is not None else None
        self.coordinator.max_current = value
        self.coordinator.async_set_updated_data(True)
        _LOGGER.info("📝 Max Current UI updated to %d A (queued for write)", value)

        await self.coordinator.queue_write(
            self._write_to_thor,
            charge_point,
            value,
            previous,
            dedupe_key=self._config_key,
        )

    async def _write_to_thor(self, charge_point, value: int, previous: int | None):
        try:
            result = await charge_point.change_configuration(
                self._config_key,
                str(value)
            )

            if result == ConfigurationStatus.accepted:
                _LOGGER.info("✅ Max Current written to Thor: %d A", value)
            elif result == ConfigurationStatus.reboot_required:
                _LOGGER.warning("⚠️ Max Current write accepted (reboot required): %d A", value)
            else:
                _LOGGER.error("❌ Max Current rejected by Thor: %s — rolling back UI to %s A", result, previous)
                if previous is not None:
                    self.coordinator.max_current = previous
                    self.coordinator.async_set_updated_data(True)

        except Exception as exc:
            _LOGGER.error("❌ Failed to set Max Current: %s", exc, exc_info=True)
            if previous is not None:
                self.coordinator.max_current = previous
                self.coordinator.async_set_updated_data(True)


# ─────────────────────────────
# Load Balancing Limit
# ─────────────────────────────

class LoadBalancingLimitNumber(BaseConfigNumber):

    _attr_name = "Loadbalancing limit"
    _attr_icon = "mdi:speedometer"
    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_min_value = 4
    _attr_native_max_value = 22
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
        value = int(round(value))

        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if not charge_point:
            _LOGGER.warning("Cannot change Load Balancing Limit: charger not connected")
            return

        current = self.coordinator.external_limit_power
        if current is not None and int(round(current)) == value:
            _LOGGER.debug("Load Balancing Limit unchanged (%d kW) - skipping write", value)
            return

        previous = int(round(current)) if current is not None else None
        self.coordinator.external_limit_power = value
        self.coordinator.async_set_updated_data(True)
        _LOGGER.info("📝 Load Balancing Limit UI updated to %d kW (queued for write)", value)

        await self.coordinator.queue_write(
            self._write_to_thor,
            charge_point,
            value,
            previous,
            dedupe_key=self._config_key,
        )

    async def _write_to_thor(self, charge_point, value: int, previous: int | None):
        try:
            result = await charge_point.change_configuration(
                self._config_key,
                str(value)
            )

            if result == ConfigurationStatus.accepted:
                _LOGGER.info("✅ Load Balancing Limit written to Thor: %d kW", value)
            elif result == ConfigurationStatus.reboot_required:
                _LOGGER.warning("⚠️ Load Balancing Limit write accepted (reboot required): %d kW", value)
            else:
                _LOGGER.error("❌ Load Balancing Limit rejected by Thor: %s — rolling back UI to %s kW", result, previous)
                if previous is not None:
                    self.coordinator.external_limit_power = previous
                    self.coordinator.async_set_updated_data(True)

        except Exception as exc:
            _LOGGER.error("❌ Failed to set Load Balancing Limit: %s", exc, exc_info=True)
            if previous is not None:
                self.coordinator.external_limit_power = previous
                self.coordinator.async_set_updated_data(True)
