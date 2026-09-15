"""Number entities for Growatt THOR load balancing."""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberDeviceClass, NumberMode
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

from ocpp.v16.enums import ConfigurationStatus

from .action_errors import (
    raise_action_validation,
    raise_charger_disconnected,
    raise_write_blocked,
)
from .const import DOMAIN
from .charging_controls import (
    ChargingControl,
    charger_write_block_reason,
    control_is_applicable,
    control_write_block_reason,
    encode_control_value,
)
from .charging_limits import (
    MIN_CHARGING_CURRENT_A,
    maximum_charging_current,
)
from .configuration import (
    configuration_entity_state,
    configuration_numeric_value,
    parse_time_sharing_price,
)
from .configuration_control import GrowattConfigurationControlMixin
from .configuration_writes import ConfigurationWriteStatus
from .currency import electricity_price_unit
from .ocpp_diagnostics import boot_notification_field
from .pv_linkage import PvBoostMode
from .write_queue import (
    CONFIGURATION_WRITE_POLICY,
    ChargerConnectionUnavailable,
    ChargerRequestOutcomeUncertain,
    ChargerWriteResult,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities([
        MaxCurrentNumber(coordinator, entry),
        LoadBalancingLimitNumber(coordinator, entry),
        ElectricityPriceNumber(coordinator, entry),
        PowerMeterAddressNumber(coordinator, entry),
        SolarGridImportLimitNumber(coordinator, entry),
        PvSmartBoostTargetEnergyNumber(coordinator, entry),
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

    @property
    def _charger_write_block_reason(self) -> str | None:
        return charger_write_block_reason(
            connected=self.coordinator.connected,
            charger_faulted=self.coordinator.charger_is_faulted,
        )

    @property
    def available(self):
        # Faults and active transactions may block writes, but neither erases a
        # value already reported by the charger.  Availability represents that
        # readable state; each setter still enforces its write guard.
        return (
            super().available
            and self.coordinator.connected
            and self.native_value is not None
        )


# ─────────────────────────────
# Max Current
# ─────────────────────────────

class MaxCurrentNumber(BaseConfigNumber):

    _attr_translation_key = "max_current"
    _attr_icon = "mdi:current-ac"
    _attr_native_min_value = MIN_CHARGING_CURRENT_A
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

    @property
    def native_max_value(self):
        """Return the maximum current supported by the reported model."""
        boot_notification = self.coordinator.boot_notification
        return maximum_charging_current(
            boot_notification_field(boot_notification, "charge_point_model"),
            boot_notification_field(boot_notification, "firmware_version"),
        )

    def _value_is_valid(self, value: int) -> bool:
        return self.native_min_value <= value <= self.native_max_value

    def _restore_previous_value(
        self,
        previous: int | None,
        generation: int,
    ) -> None:
        # A failed older request must not roll the UI back over a newer value
        # that another automation has already selected.
        if (
            previous is not None
            and self.coordinator.configuration_write_is_current(
                self._config_key,
                generation,
            )
        ):
            self.coordinator.max_current = previous
            self.coordinator.async_set_updated_data(True)

    async def async_set_native_value(self, value: float) -> None:
        if (block_reason := self._charger_write_block_reason) is not None:
            _LOGGER.warning("Cannot change Max Current: %s", block_reason)
            raise_write_blocked(block_reason)
        value = int(round(value))
        if not self._value_is_valid(value):
            _LOGGER.warning(
                "Cannot change Max Current: %d A is outside the supported "
                "range %d-%d A for the reported charger model",
                value,
                self.native_min_value,
                self.native_max_value,
            )
            raise_action_validation(
                "value_out_of_range",
                placeholders={
                    "value": f"{value} A",
                    "minimum": f"{self.native_min_value} A",
                    "maximum": f"{self.native_max_value} A",
                },
            )

        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if not charge_point:
            _LOGGER.warning("Cannot change Max Current: charger not connected")
            raise_charger_disconnected()

        current = self.coordinator.max_current
        if current is not None and int(round(current)) == value:
            _LOGGER.debug("Max Current unchanged (%d A) - skipping write", value)
            return

        reported = self.coordinator.configuration_values.get(self._config_key)
        reported_value = configuration_numeric_value(reported)
        previous = int(round(reported_value)) if reported_value is not None else None
        self.coordinator.max_current = value
        self.coordinator.async_set_updated_data(True)
        _LOGGER.info("📝 Max Current UI updated to %d A (queued for write)", value)

        # ``previous`` comes from the last reported configuration, not from the
        # optimistic UI value.  During rapid 13 → 20 → 17 changes, rolling 17
        # back to 20 would otherwise invent a charger state that never existed.
        generation = self.coordinator.begin_configuration_write(
            self._config_key,
            str(value),
        )
        await self.coordinator.queue_write(
            self._write_to_thor,
            charge_point,
            value,
            previous,
            generation,
            dedupe_key=self._config_key,
            command_name=f"ChangeConfiguration({self._config_key})",
            requires_connection=True,
            configuration_key=self._config_key,
            configuration_generation=generation,
            policy=CONFIGURATION_WRITE_POLICY,
            on_unsent=lambda _result: self._restore_previous_value(
                previous,
                generation,
            ),
        )

    async def _write_to_thor(
        self,
        charge_point,
        value: int,
        previous: int | None,
        generation: int,
    ) -> ChargerWriteResult:
        if (block_reason := self._charger_write_block_reason) is not None:
            _LOGGER.warning("Skipping queued Max Current change: %s", block_reason)
            self.coordinator.mark_configuration_write(
                self._config_key,
                ConfigurationWriteStatus.SKIPPED,
                generation=generation,
                result=block_reason,
            )
            return ChargerWriteResult.skipped(block_reason)
        if not self._value_is_valid(value):
            _LOGGER.warning(
                "Skipping queued Max Current change: %d A exceeds the current "
                "model limit of %d A",
                value,
                self.native_max_value,
            )
            self.coordinator.mark_configuration_write(
                self._config_key,
                ConfigurationWriteStatus.SKIPPED,
                generation=generation,
                result="model_limit_changed",
            )
            return ChargerWriteResult.skipped("model_limit_changed")
        try:
            result = await charge_point.change_configuration(
                self._config_key,
                str(value)
            )

            accepted = result in {
                ConfigurationStatus.accepted,
                ConfigurationStatus.reboot_required,
            }
            outcome_is_current = self.coordinator.acknowledge_configuration_write(
                self._config_key,
                generation=generation,
                accepted=accepted,
                result=result,
            )

            if result == ConfigurationStatus.accepted:
                if outcome_is_current:
                    self.coordinator.max_current = value
                    self.coordinator.update_configuration_value(
                        self._config_key,
                        str(value),
                    )
                    self.coordinator.async_set_updated_data(True)
                _LOGGER.info("✅ Max Current written to Thor: %d A", value)
            elif result == ConfigurationStatus.reboot_required:
                if outcome_is_current:
                    self.coordinator.max_current = value
                    self.coordinator.update_configuration_value(
                        self._config_key,
                        str(value),
                    )
                    self.coordinator.async_set_updated_data(True)
                _LOGGER.warning("⚠️ Max Current write accepted (reboot required): %d A", value)
            else:
                _LOGGER.error("❌ Max Current rejected by Thor: %s — rolling back UI to %s A", result, previous)
                self._restore_previous_value(previous, generation)
                return ChargerWriteResult.failed("charger_rejected", result)

            self.coordinator.schedule_configuration_refresh()
            return ChargerWriteResult.success(result)

        except ChargerConnectionUnavailable:
            raise
        except ChargerRequestOutcomeUncertain as exc:
            # Keep the requested UI value until reconnect readback resolves the
            # ambiguity; rolling back now could be just as wrong as assuming
            # success.
            self.coordinator.mark_configuration_write(
                self._config_key,
                ConfigurationWriteStatus.UNCERTAIN,
                generation=generation,
                result=str(exc),
            )
            self.coordinator.schedule_configuration_refresh(delay=0)
            return ChargerWriteResult.uncertain(str(exc))
        except Exception as exc:
            _LOGGER.error("❌ Failed to set Max Current: %s", exc, exc_info=True)
            self._restore_previous_value(previous, generation)
            return ChargerWriteResult.failed("unexpected_error")


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
            and self.coordinator.connected
            and control_is_applicable(
                ChargingControl.LOAD_BALANCING_LIMIT,
                self.coordinator.configuration_values,
            )
        )

    @property
    def _write_block_reason(self) -> str | None:
        return control_write_block_reason(
            ChargingControl.LOAD_BALANCING_LIMIT,
            self.coordinator.configuration_values,
            connected=self.coordinator.connected,
            transaction_active=self.coordinator.transaction_is_active,
            charger_faulted=self.coordinator.charger_is_faulted,
        )

    @property
    def extra_state_attributes(self):
        return {
            "information": "details",
            "ocpp_key": self._config_key,
        }

    def _restore_previous_value(
        self,
        previous: int | None,
        generation: int,
    ) -> None:
        """Restore reported power only while this write still owns the UI."""
        if (
            previous is not None
            and self.coordinator.configuration_write_is_current(
                self._config_key,
                generation,
            )
        ):
            self.coordinator.external_limit_power = previous
            self.coordinator.async_set_updated_data(True)

    async def async_set_native_value(self, value: float) -> None:
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning(
                "Cannot change Load Balancing Limit: %s",
                block_reason,
            )
            raise_write_blocked(block_reason)
        value = int(round(value))

        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if not charge_point:
            _LOGGER.warning("Cannot change Load Balancing Limit: charger not connected")
            raise_charger_disconnected()

        current = self.coordinator.external_limit_power
        if current is not None and int(round(current)) == value:
            _LOGGER.debug("Load Balancing Limit unchanged (%d kW) - skipping write", value)
            return

        reported = self.coordinator.configuration_values.get(self._config_key)
        reported_value = configuration_numeric_value(reported)
        previous = int(round(reported_value)) if reported_value is not None else None
        self.coordinator.external_limit_power = value
        self.coordinator.async_set_updated_data(True)
        _LOGGER.info("📝 Load Balancing Limit UI updated to %d kW (queued for write)", value)

        generation = self.coordinator.begin_configuration_write(
            self._config_key,
            str(value),
        )
        await self.coordinator.queue_write(
            self._write_to_thor,
            charge_point,
            value,
            previous,
            generation,
            dedupe_key=self._config_key,
            command_name=f"ChangeConfiguration({self._config_key})",
            requires_connection=True,
            configuration_key=self._config_key,
            configuration_generation=generation,
            policy=CONFIGURATION_WRITE_POLICY,
            on_unsent=lambda _result: self._restore_previous_value(
                previous,
                generation,
            ),
        )

    async def _write_to_thor(
        self,
        charge_point,
        value: int,
        previous: int | None,
        generation: int,
    ) -> ChargerWriteResult:
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning(
                "Skipping queued Load Balancing Limit change: %s",
                block_reason,
            )
            self.coordinator.mark_configuration_write(
                self._config_key,
                ConfigurationWriteStatus.SKIPPED,
                generation=generation,
                result=block_reason,
            )
            return ChargerWriteResult.skipped(block_reason)
        try:
            raw_value = str(value)
            result = await charge_point.change_configuration(
                self._config_key,
                raw_value,
            )

            accepted = result in {
                ConfigurationStatus.accepted,
                ConfigurationStatus.reboot_required,
            }
            outcome_is_current = self.coordinator.acknowledge_configuration_write(
                self._config_key,
                generation=generation,
                accepted=accepted,
                result=result,
            )
            if accepted and outcome_is_current:
                self.coordinator.update_configuration_value(
                    self._config_key,
                    raw_value,
                )
            if accepted:
                self.coordinator.schedule_configuration_refresh()

            if result == ConfigurationStatus.accepted:
                if outcome_is_current:
                    self.coordinator.external_limit_power = value
                    self.coordinator.async_set_updated_data(True)
                _LOGGER.info("✅ Load Balancing Limit written to Thor: %d kW", value)
            elif result == ConfigurationStatus.reboot_required:
                if outcome_is_current:
                    self.coordinator.external_limit_power = value
                    self.coordinator.async_set_updated_data(True)
                _LOGGER.warning("⚠️ Load Balancing Limit write accepted (reboot required): %d kW", value)
            else:
                _LOGGER.error("❌ Load Balancing Limit rejected by Thor: %s — rolling back UI to %s kW", result, previous)
                self._restore_previous_value(previous, generation)
                return ChargerWriteResult.failed("charger_rejected", result)

            return ChargerWriteResult.success(result)

        except ChargerConnectionUnavailable:
            raise
        except ChargerRequestOutcomeUncertain as exc:
            self.coordinator.mark_configuration_write(
                self._config_key,
                ConfigurationWriteStatus.UNCERTAIN,
                generation=generation,
                result=str(exc),
            )
            self.coordinator.schedule_configuration_refresh(delay=0)
            return ChargerWriteResult.uncertain(str(exc))
        except Exception as exc:
            _LOGGER.error("❌ Failed to set Load Balancing Limit: %s", exc, exc_info=True)
            self._restore_previous_value(previous, generation)
            return ChargerWriteResult.failed("unexpected_error")


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

    @property
    def extra_state_attributes(self):
        value = self.coordinator.configuration_values.get(self._config_key)
        return {
            "ocpp_key": self._config_key,
            "raw_value": value.raw_value if value is not None else None,
        }

    def _restore_previous_value(
        self,
        previous: float | None,
        generation: int,
    ) -> None:
        """Restore reported tariff only while this write still owns the UI."""
        if (
            previous is not None
            and self.coordinator.configuration_write_is_current(
                self._config_key,
                generation,
            )
        ):
            self.coordinator.electricity_price = previous
            self.coordinator.async_set_updated_data(True)

    async def async_set_native_value(self, value: float) -> None:
        if (block_reason := self._charger_write_block_reason) is not None:
            _LOGGER.warning("Cannot change Electricity Price: %s", block_reason)
            raise_write_blocked(block_reason)
        value = round(value, 2)

        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if not charge_point:
            _LOGGER.warning("Cannot change Elektricteitstarief: charger not connected")
            raise_charger_disconnected()

        current = self.coordinator.electricity_price
        if current is not None and round(current, 2) == value:
            _LOGGER.debug("Electricity price unchanged (%.2f per kWh) - skipping write", value)
            return

        reported = self.coordinator.configuration_values.get(self._config_key)
        reported_value = parse_time_sharing_price(
            reported.raw_value if reported is not None else None
        )
        previous = round(reported_value, 2) if reported_value is not None else None
        self.coordinator.electricity_price = value
        self.coordinator.async_set_updated_data(True)
        _LOGGER.info("📝 Electricity price updated to %.2f per kWh (queued for write)", value)

        price_str = f"time1=00:00-23:59&price1={value:.2f}"
        generation = self.coordinator.begin_configuration_write(
            self._config_key,
            price_str,
        )
        await self.coordinator.queue_write(
            self._write_to_thor,
            charge_point,
            value,
            previous,
            generation,
            dedupe_key=self._config_key,
            command_name=f"ChangeConfiguration({self._config_key})",
            requires_connection=True,
            configuration_key=self._config_key,
            configuration_generation=generation,
            policy=CONFIGURATION_WRITE_POLICY,
            on_unsent=lambda _result: self._restore_previous_value(
                previous,
                generation,
            ),
        )

    async def _write_to_thor(
        self,
        charge_point,
        value: float,
        previous: float | None,
        generation: int,
    ) -> ChargerWriteResult:
        if (block_reason := self._charger_write_block_reason) is not None:
            _LOGGER.warning(
                "Skipping queued Electricity Price change: %s",
                block_reason,
            )
            self.coordinator.mark_configuration_write(
                self._config_key,
                ConfigurationWriteStatus.SKIPPED,
                generation=generation,
                result=block_reason,
            )
            return ChargerWriteResult.skipped(block_reason)
        price_str = f"time1=00:00-23:59&price1={value:.2f}"  # ← gecorrigeerd: formaat conform THOR response
        try:
            result = await charge_point.change_configuration(
                self._config_key,
                price_str,
            )

            accepted = result in {
                ConfigurationStatus.accepted,
                ConfigurationStatus.reboot_required,
            }
            outcome_is_current = self.coordinator.acknowledge_configuration_write(
                self._config_key,
                generation=generation,
                accepted=accepted,
                result=result,
            )

            if result == ConfigurationStatus.accepted:
                if outcome_is_current:
                    self.coordinator.electricity_price = value
                    self.coordinator.update_configuration_value(
                        self._config_key,
                        price_str,
                    )
                    self.coordinator.async_set_updated_data(True)
                _LOGGER.info("✅ Elektricteitstarief written to Thor: %s", price_str)
            elif result == ConfigurationStatus.reboot_required:
                if outcome_is_current:
                    self.coordinator.electricity_price = value
                    self.coordinator.update_configuration_value(
                        self._config_key,
                        price_str,
                    )
                    self.coordinator.async_set_updated_data(True)
                _LOGGER.warning("⚠️ Elektricteitstarief write accepted (reboot required): %s", price_str)
            else:
                _LOGGER.error("❌ Elektricteitstarief rejected by Thor: %s — rolling back to %.2f", result, previous)
                self._restore_previous_value(previous, generation)
                return ChargerWriteResult.failed("charger_rejected", result)

            self.coordinator.schedule_configuration_refresh()
            return ChargerWriteResult.success(result)

        except ChargerConnectionUnavailable:
            raise
        except ChargerRequestOutcomeUncertain as exc:
            self.coordinator.mark_configuration_write(
                self._config_key,
                ConfigurationWriteStatus.UNCERTAIN,
                generation=generation,
                result=str(exc),
            )
            self.coordinator.schedule_configuration_refresh(delay=0)
            return ChargerWriteResult.uncertain(str(exc))
        except Exception as exc:
            _LOGGER.error("❌ Failed to set Elektricteitstarief: %s", exc, exc_info=True)
            self._restore_previous_value(previous, generation)
            return ChargerWriteResult.failed("unexpected_error")


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


class PowerMeterAddressNumber(
    GrowattConfigurationControlMixin,
    CoordinatorEntity,
    NumberEntity,
):
    """Configure the Modbus address of the external power meter."""

    _control = ChargingControl.POWER_METER_ADDRESS
    _attr_has_entity_name = True
    _attr_translation_key = "power_meter_address"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_mode = NumberMode.BOX
    _attr_native_min_value = 1
    _attr_native_max_value = 247
    _attr_native_step = 1
    _attr_icon = "mdi:numeric"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self.hass = coordinator.hass
        self._attr_unique_id = f"{entry.entry_id}_power_meter_address_control"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id, "grid_connection")},
            "name": "Growatt THOR External Meter",
            "manufacturer": "Growatt",
            "model": "THOR External Meter",
        }

    @property
    def native_value(self):
        value = configuration_entity_state(
            self._configuration_key,
            self._configuration_value,
        )
        return int(value) if isinstance(value, (int, float)) else None

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


class PvSmartBoostTargetEnergyNumber(BaseConfigNumber):
    """Edit the local Smart Boost target energy draft."""

    _attr_translation_key = "pv_smart_boost_target_energy"
    _attr_icon = "mdi:battery-charging-high"
    _attr_device_class = NumberDeviceClass.ENERGY
    _attr_native_min_value = 0.1
    _attr_native_max_value = 200
    _attr_native_step = 0.1
    _attr_native_unit_of_measurement = "kWh"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "pv_smart_boost_target_energy")
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }

    @property
    def native_value(self):
        return self.coordinator.pv_smart_target_energy_draft

    @property
    def _write_block_reason(self) -> str | None:
        return control_write_block_reason(
            ChargingControl.SOLAR_BOOST,
            self.coordinator.configuration_values,
            connected=self.coordinator.connected,
            transaction_active=self.coordinator.transaction_is_active,
            charger_faulted=self.coordinator.charger_is_faulted,
        )

    @property
    def available(self):
        # Keep a populated local draft visible even while applying it is unsafe.
        return (
            super().available
            and control_is_applicable(
                ChargingControl.SOLAR_BOOST,
                self.coordinator.configuration_values,
            )
            and self.coordinator.pv_boost_mode_draft == PvBoostMode.SMART
        )

    @property
    def extra_state_attributes(self):
        return {"information": "details"}

    async def async_set_native_value(self, value: float) -> None:
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning(
                "Cannot edit Smart Boost target energy: %s",
                block_reason,
            )
            raise_write_blocked(block_reason)
        self.coordinator.update_pv_linkage_draft(
            pv_smart_target_energy_draft=round(float(value), 3)
        )
