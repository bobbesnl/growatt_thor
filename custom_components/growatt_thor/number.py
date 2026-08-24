"""Number entities for Growatt THOR load balancing."""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberDeviceClass, NumberMode
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

from ocpp.v16.enums import ConfigurationStatus

from .const import DOMAIN
from .charging_controls import (
    ChargingControl,
    control_write_block_reason,
    encode_control_value,
)
from .configuration import configuration_entity_state
from .configuration_control import (
    GrowattConfigurationControlMixin,
    async_confirm_configuration,
)
from .currency import electricity_price_unit

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities([
        MaxCurrentNumber(coordinator, entry),
        LoadBalancingLimitNumber(coordinator, entry),
        ElectricityPriceNumber(coordinator, entry),
        SolarGridImportLimitNumber(coordinator, entry),
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

    _attr_translation_key = "max_current"
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
                self.coordinator.max_current = value
                self.coordinator.async_set_updated_data(True)
                _LOGGER.info("✅ Max Current written to Thor: %d A", value)
            elif result == ConfigurationStatus.reboot_required:
                self.coordinator.max_current = value
                self.coordinator.async_set_updated_data(True)
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

    _attr_translation_key = "load_balancing_limit"
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
            "name": "Growatt THOR External Meter",
            "manufacturer": "Growatt",
            "model": "THOR External Meter",
        }

    @property
    def native_value(self):
        value = self.coordinator.external_limit_power
        return int(value) if value is not None else 10

    @property
    def available(self):
        return (
            super().available
            and self._write_block_reason is None
        )

    @property
    def _write_block_reason(self) -> str | None:
        return control_write_block_reason(
            ChargingControl.LOAD_BALANCING_LIMIT,
            self.coordinator.configuration_values,
            connected=self.coordinator.connected,
            transaction_active=self.coordinator.transaction_is_active,
        )

    async def async_set_native_value(self, value: float) -> None:
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning(
                "Cannot change Load Balancing Limit: %s",
                block_reason,
            )
            return
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
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning(
                "Skipping queued Load Balancing Limit change: %s",
                block_reason,
            )
            return
        try:
            raw_value = str(value)
            self.coordinator.begin_configuration_write(
                self._config_key,
                raw_value,
            )
            result = await charge_point.change_configuration(
                self._config_key,
                raw_value,
            )

            accepted = result in {
                ConfigurationStatus.accepted,
                ConfigurationStatus.reboot_required,
            }
            self.coordinator.acknowledge_configuration_write(
                self._config_key,
                accepted=accepted,
                result=result,
            )
            if accepted:
                self.hass.async_create_task(
                    async_confirm_configuration(self.hass, charge_point)
                )

            if result == ConfigurationStatus.accepted:
                self.coordinator.external_limit_power = value
                self.coordinator.async_set_updated_data(True)
                _LOGGER.info("✅ Load Balancing Limit written to Thor: %d kW", value)
            elif result == ConfigurationStatus.reboot_required:
                self.coordinator.external_limit_power = value
                self.coordinator.async_set_updated_data(True)
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


# ─────────────────────────────
# Electricity price
# ─────────────────────────────

class ElectricityPriceNumber(BaseConfigNumber):

    _attr_translation_key = "electricity_price"
    _attr_icon = "mdi:cash"
    _attr_native_min_value = -2.0
    _attr_native_max_value = 2.0
    _attr_native_step = 0.01
    _attr_suggested_display_precision = 2
    _config_key = "G_TimeSharingPrice"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "electricity_price")
        self._attr_native_unit_of_measurement = electricity_price_unit(
            coordinator.hass
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }

    @property
    def native_value(self):
        return self.coordinator.electricity_price

    async def async_set_native_value(self, value: float) -> None:
        value = round(value, 2)

        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if not charge_point:
            _LOGGER.warning("Cannot change Elektricteitstarief: charger not connected")
            return

        current = self.coordinator.electricity_price
        if current is not None and round(current, 2) == value:
            _LOGGER.debug("Electricity price unchanged (%.2f per kWh) - skipping write", value)
            return

        previous = round(current, 2) if current is not None else None
        self.coordinator.electricity_price = value
        self.coordinator.async_set_updated_data(True)
        _LOGGER.info("📝 Electricity price updated to %.2f per kWh (queued for write)", value)

        await self.coordinator.queue_write(
            self._write_to_thor,
            charge_point,
            value,
            previous,
            dedupe_key=self._config_key,
        )

    async def _write_to_thor(self, charge_point, value: float, previous: float | None):
        price_str = f"time1=00:00-23:59&price1={value:.2f}"  # ← gecorrigeerd: formaat conform THOR response
        try:
            result = await charge_point.change_configuration(
                self._config_key,
                price_str,
            )

            if result == ConfigurationStatus.accepted:
                self.coordinator.electricity_price = value
                self.coordinator.async_set_updated_data(True)
                _LOGGER.info("✅ Elektricteitstarief written to Thor: %s", price_str)
            elif result == ConfigurationStatus.reboot_required:
                self.coordinator.electricity_price = value
                self.coordinator.async_set_updated_data(True)
                _LOGGER.warning("⚠️ Elektricteitstarief write accepted (reboot required): %s", price_str)
            else:
                _LOGGER.error("❌ Elektricteitstarief rejected by Thor: %s — rolling back to %.2f", result, previous)
                if previous is not None:
                    self.coordinator.electricity_price = previous
                    self.coordinator.async_set_updated_data(True)

        except Exception as exc:
            _LOGGER.error("❌ Failed to set Elektricteitstarief: %s", exc, exc_info=True)
            if previous is not None:
                self.coordinator.electricity_price = previous
                self.coordinator.async_set_updated_data(True)


class SolarGridImportLimitNumber(
    GrowattConfigurationControlMixin,
    CoordinatorEntity,
    NumberEntity,
):
    """Configure the grid power allowance used by PV Linkage."""

    _control = ChargingControl.SOLAR_GRID_IMPORT_LIMIT
    _attr_has_entity_name = True
    _attr_translation_key = "solar_grid_import_limit"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 22
    _attr_native_step = 0.1
    _attr_native_unit_of_measurement = "kW"
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:transmission-tower-import"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self.hass = coordinator.hass
        self._attr_unique_id = f"{entry.entry_id}_solar_grid_import_limit_control"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }

    @property
    def native_value(self):
        value = configuration_entity_state(
            self._configuration_key,
            self._configuration_value,
        )
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def available(self):
        return (
            super().available
            and self._control_available
            and self.native_value is not None
        )

    async def async_set_native_value(self, value: float) -> None:
        await self._async_write_configuration(
            encode_control_value(self._control, value)
        )
