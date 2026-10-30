"""Number entities for Growatt THOR load balancing."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

import logging

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.helpers.entity import EntityCategory
from ocpp.v16.enums import ConfigurationStatus

from .charging.control_capabilities import (
    ChargingControl,
    charger_write_block_reason,
    control_is_applicable,
    encode_control_value,
)
from .charging.limits import (
    MIN_CHARGING_CURRENT_A,
    maximum_charging_current,
)
from .charging.pv_linkage import PvBoostMode
from .configuration.controls import GrowattConfigurationControlMixin, GrowattConfigurationWriteMixin
from .configuration.validation import (
    NumericValidationError,
    NumericValidationReason,
    validate_number,
)
from .configuration.values import (
    configuration_entity_state,
    configuration_numeric_value,
    parse_time_sharing_price,
)
from .configuration.writes import ConfigurationWriteStatus
from .const import DOMAIN
from .energy.currency import electricity_price_unit
from .entity import ThorEntity
from .ocpp.diagnostics import boot_notification_field
from .runtime.action_errors import (
    async_require_command_completion,
    raise_action_validation,
    raise_charger_disconnected,
    raise_write_blocked,
)
from .runtime.write_results import (
    CONFIGURATION_WRITE_POLICY,
    ChargerConnectionUnavailable,
    ChargerRequestOutcomeUncertain,
    ChargerWriteResult,
)

_LOGGER = logging.getLogger(__name__)


def _display_number(entity, value: object) -> str:
    """Add the entity unit to validation errors without changing the value."""
    unit = entity.native_unit_of_measurement
    return f"{value} {unit}" if unit else str(value)


def _validated_entity_number(
    entity,
    value: object,
    *,
    integer: bool = False,
) -> int | float:
    """Validate one HA number request against its advertised exact contract."""
    minimum = entity.native_min_value
    maximum = entity.native_max_value
    step = entity.native_step
    try:
        numeric = validate_number(
            value,
            minimum=minimum,
            maximum=maximum,
            step=step,
        )
    except NumericValidationError as exc:
        if exc.reason == NumericValidationReason.NOT_FINITE:
            raise_action_validation(
                "value_not_finite",
                placeholders={"value": value},
            )
        if exc.reason == NumericValidationReason.OUT_OF_RANGE:
            raise_action_validation(
                "value_out_of_range",
                placeholders={
                    "value": _display_number(entity, value),
                    "minimum": _display_number(entity, minimum),
                    "maximum": _display_number(entity, maximum),
                },
            )
        if exc.reason == NumericValidationReason.STEP_MISMATCH:
            raise_action_validation(
                "value_step_mismatch",
                placeholders={
                    "value": _display_number(entity, value),
                    "step": _display_number(entity, step),
                },
            )
        raise_action_validation(
            "invalid_numeric_value",
            placeholders={"value": value},
        )

    return int(numeric) if integer else float(numeric)


def _validated_reported_entity_number(
    entity,
    value: object,
    *,
    integer: bool = False,
) -> int | float | None:
    """Normalize charger readback only when it matches the entity contract."""
    if value is None:
        return None
    try:
        numeric = validate_number(
            value,
            minimum=entity.native_min_value,
            maximum=entity.native_max_value,
            step=entity.native_step,
        )
    except NumericValidationError:
        # A malformed readback must neither crash a valid user command nor be
        # restored optimistically after that command fails.
        _LOGGER.warning(
            "Ignoring invalid reported value %r for %s",
            value,
            entity._attr_translation_key,
        )
        return None
    return int(numeric) if integer else float(numeric)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    async_add_entities(
        [
            MaxCurrentNumber(coordinator, entry),
            LoadBalancingLimitNumber(coordinator, entry),
            ElectricityPriceNumber(coordinator, entry),
            PowerMeterAddressNumber(coordinator, entry),
            SolarGridImportLimitNumber(coordinator, entry),
            PvSmartBoostTargetEnergyNumber(coordinator, entry),
        ]
    )


# Base class


class BaseConfigNumber(ThorEntity, NumberEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_mode = NumberMode.BOX

    def __init__(self, coordinator, entry, key, *, device="charger"):
        super().__init__(coordinator, entry, device=device)
        self._attr_unique_id = f"{entry.entry_id}_{key}"

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
        return super().available and self.coordinator.connected and self.native_value is not None


# Max Current


class ConfigurationNumberWriteMixin(GrowattConfigurationWriteMixin):
    """Execute a domain-valued number write with one rollback/error boundary."""

    _refresh_in_accept = False

    def _queued_write_block_reason(self):
        return self._charger_write_block_reason

    def _queued_value_block_reason(self, value):
        return None

    async def _write_to_thor(self, charge_point, value, previous, generation):
        reason = self._queued_write_block_reason() or self._queued_value_block_reason(value)
        if reason is not None:
            self.coordinator.mark_configuration_write(
                self._config_key,
                ConfigurationWriteStatus.SKIPPED,
                generation=generation,
                result=reason,
            )
            return ChargerWriteResult.skipped(reason)
        try:
            raw_value = self._encode(value)
            response = await self._configuration_exchange(
                charge_point, self._config_key, raw_value, generation
            )
            if not response.accepted:
                self._restore_optimistic(generation, previous=previous)
                return ChargerWriteResult.failed("charger_rejected", response.result)
            if response.current:
                self._on_accepted(raw_value, key=self._config_key, value=value)
            if not self._refresh_in_accept or not response.current:
                self.coordinator.schedule_configuration_refresh()
            if response.result == ConfigurationStatus.reboot_required:
                _LOGGER.warning("%s accepted; charger reboot required", self._config_key)
            return ChargerWriteResult.success(response.result)
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
        except Exception:
            _LOGGER.exception("Failed to set %s", self._config_key)
            self._restore_optimistic(generation, previous=previous)
            return ChargerWriteResult.failed("unexpected_error")


class MaxCurrentNumber(ConfigurationNumberWriteMixin, BaseConfigNumber):
    _attr_translation_key = "max_current"
    _attr_icon = "mdi:current-ac"
    _attr_native_min_value = MIN_CHARGING_CURRENT_A
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "A"
    _config_key = "G_MaxCurrent"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "max_current")

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

    def _validate_write_value(self, value):
        return _validated_entity_number(self, value, integer=True)

    def _encode(self, value) -> str:
        return str(value)

    def _on_accepted(self, raw_value, *, value, key=None) -> None:
        self.coordinator.max_current = value
        super()._on_accepted(raw_value, key=key, value=value)
        self.coordinator.async_set_updated_data(True)

    def _queued_value_block_reason(self, value):
        return None if self._value_is_valid(value) else "model_limit_changed"

    def _value_is_valid(self, value: int) -> bool:
        return self.native_min_value <= value <= self.native_max_value

    def _restore_optimistic(self, generation: int, *, previous=None) -> None:
        # A failed older request must not roll the UI back over a newer value
        # that another automation has already selected.
        if previous is not None and self.coordinator.configuration_write_is_current(
            self._config_key,
            generation,
        ):
            self.coordinator.max_current = previous
            self.coordinator.async_set_updated_data(True)

    async def async_set_native_value(self, value: float) -> None:
        value = self._validate_write_value(value)
        if (block_reason := self._charger_write_block_reason) is not None:
            _LOGGER.warning("Cannot change Max Current: %s", block_reason)
            raise_write_blocked(block_reason)

        charge_point = self.coordinator.runtime_data.get("charge_point")
        if not charge_point:
            _LOGGER.warning("Cannot change Max Current: charger not connected")
            raise_charger_disconnected()

        current = _validated_reported_entity_number(
            self,
            self.coordinator.max_current,
            integer=True,
        )
        if current == value:
            _LOGGER.debug("Max Current unchanged (%d A) - skipping write", value)
            return

        reported = self.coordinator.configuration_values.get(self._config_key)
        reported_value = configuration_numeric_value(reported)
        previous = _validated_reported_entity_number(
            self,
            reported_value,
            integer=True,
        )
        self.coordinator.max_current = value
        self.coordinator.async_set_updated_data(True)
        _LOGGER.info("Max Current UI updated to %d A (queued for write)", value)

        # ``previous`` comes from the last reported configuration, not from the
        # optimistic UI value.  During rapid 13 → 20 → 17 changes, rolling 17
        # back to 20 would otherwise invent a charger state that never existed.
        generation = self.coordinator.begin_configuration_write(
            self._config_key,
            self._encode(value),
        )
        handle = await self.coordinator.queue_write(
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
            on_unsent=lambda _result: self._restore_optimistic(
                generation,
                previous=previous,
            ),
        )
        await async_require_command_completion(handle)


# Load Balancing Limit


class LoadBalancingLimitNumber(ConfigurationNumberWriteMixin, BaseConfigNumber):
    _attr_translation_key = "load_balancing_limit"
    _attr_icon = "mdi:speedometer"
    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_min_value = 4
    _attr_native_max_value = 22
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "kW"
    _config_key = "G_ExternalLimitPower"
    # This entity historically schedules readback before publishing its mirror.
    _refresh_in_accept = True

    def _queued_write_block_reason(self):
        return self._write_block_reason

    def _on_accepted(self, raw_value, *, value, key=None) -> None:
        super()._on_accepted(raw_value, key=key, value=value)
        self.coordinator.schedule_configuration_refresh()
        self.coordinator.external_limit_power = value
        self.coordinator.async_set_updated_data(True)

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "load_balancing_limit", device="meter")

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
        return self.coordinator.write_block_reason(ChargingControl.LOAD_BALANCING_LIMIT)

    @property
    def extra_state_attributes(self):
        return {
            **self.information_attributes,
            "ocpp_key": self._config_key,
        }

    def _validate_write_value(self, value):
        return _validated_entity_number(self, value, integer=True)

    def _encode(self, value) -> str:
        return str(value)

    def _restore_optimistic(self, generation: int, *, previous=None) -> None:
        """Restore reported power only while this write still owns the UI."""
        if previous is not None and self.coordinator.configuration_write_is_current(
            self._config_key,
            generation,
        ):
            self.coordinator.external_limit_power = previous
            self.coordinator.async_set_updated_data(True)

    async def async_set_native_value(self, value: float) -> None:
        value = self._validate_write_value(value)
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning(
                "Cannot change Load Balancing Limit: %s",
                block_reason,
            )
            raise_write_blocked(block_reason)

        charge_point = self.coordinator.runtime_data.get("charge_point")
        if not charge_point:
            _LOGGER.warning("Cannot change Load Balancing Limit: charger not connected")
            raise_charger_disconnected()

        current = _validated_reported_entity_number(
            self,
            self.coordinator.external_limit_power,
            integer=True,
        )
        if current == value:
            _LOGGER.debug("Load Balancing Limit unchanged (%d kW) - skipping write", value)
            return

        reported = self.coordinator.configuration_values.get(self._config_key)
        reported_value = configuration_numeric_value(reported)
        previous = _validated_reported_entity_number(
            self,
            reported_value,
            integer=True,
        )
        self.coordinator.external_limit_power = value
        self.coordinator.async_set_updated_data(True)
        _LOGGER.info("Load Balancing Limit UI updated to %d kW (queued for write)", value)

        generation = self.coordinator.begin_configuration_write(
            self._config_key,
            self._encode(value),
        )
        handle = await self.coordinator.queue_write(
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
            on_unsent=lambda _result: self._restore_optimistic(
                generation,
                previous=previous,
            ),
        )
        await async_require_command_completion(handle)


# Electricity price


class ElectricityPriceNumber(ConfigurationNumberWriteMixin, BaseConfigNumber):
    _attr_translation_key = "electricity_price"
    _attr_icon = "mdi:cash"
    _attr_native_min_value = -2.0
    _attr_native_max_value = 2.0
    _attr_native_step = 0.01
    _attr_suggested_display_precision = 2
    _config_key = "G_TimeSharingPrice"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "electricity_price")
        self._attr_native_unit_of_measurement = electricity_price_unit(coordinator.hass)

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

    def _validate_write_value(self, value):
        return _validated_entity_number(self, value)

    def _encode(self, value) -> str:
        # Match the full-day time-period format returned by THOR.
        return f"time1=00:00-23:59&price1={value:.2f}"

    def _on_accepted(self, raw_value, *, value, key=None) -> None:
        self.coordinator.electricity_price = value
        super()._on_accepted(raw_value, key=key, value=value)
        self.coordinator.async_set_updated_data(True)

    def _restore_optimistic(self, generation: int, *, previous=None) -> None:
        """Restore reported tariff only while this write still owns the UI."""
        if previous is not None and self.coordinator.configuration_write_is_current(
            self._config_key,
            generation,
        ):
            self.coordinator.electricity_price = previous
            self.coordinator.async_set_updated_data(True)

    async def async_set_native_value(self, value: float) -> None:
        value = self._validate_write_value(value)
        if (block_reason := self._charger_write_block_reason) is not None:
            _LOGGER.warning("Cannot change Electricity Price: %s", block_reason)
            raise_write_blocked(block_reason)

        charge_point = self.coordinator.runtime_data.get("charge_point")
        if not charge_point:
            _LOGGER.warning("Cannot change Electricity tariff: charger not connected")
            raise_charger_disconnected()

        current = _validated_reported_entity_number(
            self,
            self.coordinator.electricity_price,
        )
        if current == value:
            _LOGGER.debug("Electricity price unchanged (%.2f per kWh) - skipping write", value)
            return

        reported = self.coordinator.configuration_values.get(self._config_key)
        reported_value = parse_time_sharing_price(
            reported.raw_value if reported is not None else None
        )
        previous = _validated_reported_entity_number(self, reported_value)
        self.coordinator.electricity_price = value
        self.coordinator.async_set_updated_data(True)
        _LOGGER.info("Electricity price updated to %.2f per kWh (queued for write)", value)

        price_str = self._encode(value)
        generation = self.coordinator.begin_configuration_write(
            self._config_key,
            price_str,
        )
        handle = await self.coordinator.queue_write(
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
            on_unsent=lambda _result: self._restore_optimistic(
                generation,
                previous=previous,
            ),
        )
        await async_require_command_completion(handle)


class SolarGridImportLimitNumber(
    GrowattConfigurationControlMixin,
    ThorEntity,
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
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_solar_grid_import_limit_control"

    @property
    def native_value(self):
        value = configuration_entity_state(
            self._configuration_key,
            self._configuration_value,
        )
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def available(self):
        return super().available and self._control_available and self.native_value is not None

    async def async_set_native_value(self, value: float) -> None:
        value = _validated_entity_number(self, value)
        await self._async_write_configuration(encode_control_value(self._control, value))


class PowerMeterAddressNumber(
    GrowattConfigurationControlMixin,
    ThorEntity,
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
        super().__init__(coordinator, entry, device="meter")
        self._attr_unique_id = f"{entry.entry_id}_power_meter_address_control"

    @property
    def native_value(self):
        value = configuration_entity_state(
            self._configuration_key,
            self._configuration_value,
        )
        return int(value) if isinstance(value, (int, float)) else None

    @property
    def available(self):
        return super().available and self._control_available and self.native_value is not None

    async def async_set_native_value(self, value: float) -> None:
        value = _validated_entity_number(self, value, integer=True)
        await self._async_write_configuration(encode_control_value(self._control, value))


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

    @property
    def native_value(self):
        return self.coordinator.pv_smart_target_energy_draft

    @property
    def _write_block_reason(self) -> str | None:
        return self.coordinator.write_block_reason(ChargingControl.SOLAR_BOOST)

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
        return self.information_attributes

    async def async_set_native_value(self, value: float) -> None:
        value = _validated_entity_number(self, value)
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning(
                "Cannot edit Smart Boost target energy: %s",
                block_reason,
            )
            raise_write_blocked(block_reason)
        self.coordinator.update_pv_linkage_draft(pv_smart_target_energy_draft=value)
