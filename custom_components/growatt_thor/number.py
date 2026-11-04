"""Number entities for Growatt THOR load balancing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import GrowattCoordinator
    from .runtime.entry import ThorConfigEntry

import logging

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import EntityCategory
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
from .configuration.controls import ConfigurationControl
from .configuration.validation import (
    NumericValidationError,
    NumericValidationReason,
    validate_number,
)
from .configuration.values import (
    configuration_numeric_value,
    parse_time_sharing_price,
)
from .configuration.writer import ConfigurationWrite, ConfigurationWriter, WritePolicy
from .energy.currency import electricity_price_unit
from .entity import ThorEntity
from .ocpp.core.diagnostics import boot_notification_field
from .runtime.action_errors import (
    raise_action_validation,
    raise_write_blocked,
)
from .runtime.write_results import (
    ChargerWriteResult,
)

_LOGGER = logging.getLogger(__name__)


def _display_number(entity: NumberEntity, value: object) -> str:
    """Add the entity unit to validation errors without changing the value."""
    unit = entity.native_unit_of_measurement
    return f"{value} {unit}" if unit else str(value)


def _validated_entity_number(
    entity: NumberEntity,
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
    entity: NumberEntity,
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
    hass: HomeAssistant, entry: ThorConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    # HA forwards platforms only after this entry has claimed its coordinator.
    coordinator = cast("GrowattCoordinator", entry.runtime_data.coordinator)

    async_add_entities(
        [
            MaxCurrentNumber(coordinator, entry),
            LoadBalancingLimitNumber(coordinator, entry),
            ElectricityPriceNumber(coordinator, entry),
            *(
                ConfigurationControlNumber(coordinator, entry, description)
                for description in CONTROL_NUMBERS
            ),
            PvSmartBoostTargetEnergyNumber(coordinator, entry),
        ]
    )


# Base class


class BaseConfigNumber(ThorEntity, NumberEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: GrowattCoordinator,
        entry: ConfigEntry,
        key: str,
        *,
        device: Literal["charger", "meter"] = "charger",
    ) -> None:
        super().__init__(coordinator, entry, device=device)
        self._attr_unique_id = f"{entry.entry_id}_{key}"

    @property
    def _charger_write_block_reason(self) -> str | None:
        return charger_write_block_reason(
            connected=self.coordinator.connected,
            charger_faulted=self.coordinator.charger_is_faulted,
            reboot_pending=self.coordinator.charger_reboot_pending,
        )

    @property
    def available(self) -> bool:
        # Faults and active transactions may block writes, but neither erases a
        # value already reported by the charger.  Availability represents that
        # readable state; each setter still enforces its write guard.
        return super().available and self.coordinator.connected and self.native_value is not None


# Optimistic number writes


class OptimisticNumberPolicy(WritePolicy[float]):
    """Write one optimistic domain number as one configuration key.

    The coordinator attribute named by ``mirror`` holds the value HA shows.
    ``previous`` comes from the last reported configuration, not from the
    optimistic UI value. During rapid 13 → 20 → 17 changes, rolling 17 back to
    20 would otherwise invent a charger state that never existed.
    """

    # Number writes keep acknowledgement and accepted state inside the error
    # boundary: an unexpected failure restores the owning optimistic value and
    # returns a terminal failure to the queue.
    guards_outcome = True
    mirror: str
    integer = True
    unchanged_message: str
    queued_message: str

    def __init__(self, entity: BaseConfigNumber, key: str) -> None:
        super().__init__(entity.coordinator)
        self.entity = entity
        self.coordinator = entity.coordinator
        self.key = key

    def encode(self, value: float) -> tuple[str, str]:
        return self.key, str(value)

    def request_block_reason(self) -> str | None:
        return self.entity._charger_write_block_reason

    def reported_value(self) -> object:
        return configuration_numeric_value(self.coordinator.configuration_values.get(self.key))

    def _validated(self, value: object) -> int | float | None:
        return _validated_reported_entity_number(self.entity, value, integer=self.integer)

    def is_unchanged(self, value: float) -> bool:
        if self._validated(getattr(self.coordinator, self.mirror)) != value:
            return False
        _LOGGER.debug(self.unchanged_message, value)
        return True

    def apply_optimistic(self, value: float) -> object:
        previous = self._validated(self.reported_value())
        setattr(self.coordinator, self.mirror, value)
        self.coordinator.async_set_updated_data(True)
        _LOGGER.info(self.queued_message, value)
        return previous

    def apply_accepted(self, write: ConfigurationWrite[float]) -> None:
        setattr(self.coordinator, self.mirror, write.value)
        super().apply_accepted(write)
        self.coordinator.async_set_updated_data(True)

    def _restore(self, write: ConfigurationWrite[float]) -> None:
        # A failed older request must not roll the UI back over a newer value
        # that another automation has already selected.
        if write.previous is not None and self.coordinator.configuration_write_is_current(
            write.key,
            write.generation,
        ):
            setattr(self.coordinator, self.mirror, write.previous)
            self.coordinator.async_set_updated_data(True)

    def on_unsent(self, write: ConfigurationWrite[float]) -> None:
        self._restore(write)

    def on_rejected(self, write: ConfigurationWrite[float], result: object) -> None:
        self._restore(write)

    def on_unexpected(
        self, write: ConfigurationWrite[float], exc: Exception
    ) -> ChargerWriteResult | None:
        # Restore only the owning optimistic value and return a terminal failure to the queue.
        _LOGGER.exception("Failed to set %s", write.key)
        self._restore(write)
        return ChargerWriteResult.failed("unexpected_error")

    def report_accepted(self, write: ConfigurationWrite[float], result: object) -> None:
        if result == ConfigurationStatus.reboot_required:
            _LOGGER.warning("%s accepted; charger reboot required", write.key)


class MaxCurrentWritePolicy(OptimisticNumberPolicy):
    label = "Max Current"
    mirror = "max_current"
    unchanged_message = "Max Current unchanged (%d A) - skipping write"
    queued_message = "Max Current UI updated to %d A (queued for write)"

    def queued_block_reason(self, write: ConfigurationWrite[float]) -> str | None:
        # The reported model may have changed while the write waited.
        return self.request_block_reason() or (
            None
            if self.entity.native_min_value <= write.value <= self.entity.native_max_value
            else "model_limit_changed"
        )


class LoadBalancingLimitWritePolicy(OptimisticNumberPolicy):
    label = "Load Balancing Limit"
    mirror = "external_limit_power"
    unchanged_message = "Load Balancing Limit unchanged (%d kW) - skipping write"
    queued_message = "Load Balancing Limit UI updated to %d kW (queued for write)"
    # This entity historically schedules readback before publishing its mirror.
    refreshes_on_apply = True

    def request_block_reason(self) -> str | None:
        return self.coordinator.write_block_reason(ChargingControl.LOAD_BALANCING_LIMIT)

    def apply_accepted(self, write: ConfigurationWrite[float]) -> None:
        self.coordinator.update_configuration_value(write.key, write.raw_value)
        self.coordinator.schedule_configuration_refresh()
        self.coordinator.external_limit_power = write.value
        self.coordinator.async_set_updated_data(True)


class ElectricityPriceWritePolicy(OptimisticNumberPolicy):
    label = "Electricity Price"
    mirror = "electricity_price"
    integer = False
    unchanged_message = "Electricity price unchanged (%.2f per kWh) - skipping write"
    queued_message = "Electricity price updated to %.2f per kWh (queued for write)"

    def encode(self, value: float) -> tuple[str, str]:
        # Match the full-day time-period format returned by THOR.
        return self.key, f"time1=00:00-23:59&price1={value:.2f}"

    def reported_value(self) -> object:
        reported = self.coordinator.configuration_values.get(self.key)
        return parse_time_sharing_price(reported.raw_value if reported is not None else None)


# Max Current


class MaxCurrentNumber(BaseConfigNumber):
    coordinator: GrowattCoordinator
    _attr_translation_key = "max_current"
    _attr_icon = "mdi:current-ac"
    _attr_native_min_value = MIN_CHARGING_CURRENT_A
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "A"
    _config_key = "G_MaxCurrent"

    def __init__(self, coordinator: GrowattCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "max_current")
        self._writer = ConfigurationWriter(
            coordinator, MaxCurrentWritePolicy(self, self._config_key)
        )

    @property
    def native_value(self) -> float | None:
        value = self.coordinator.max_current
        return int(value) if value is not None else None

    @property
    def native_max_value(self) -> float:
        """Return the maximum current supported by the reported model."""
        boot_notification = self.coordinator.boot_notification
        return maximum_charging_current(
            boot_notification_field(boot_notification, "charge_point_model"),
            boot_notification_field(boot_notification, "firmware_version"),
        )

    def _validate_write_value(self, value: object) -> int | float:
        return _validated_entity_number(self, value, integer=True)

    async def async_set_native_value(self, value: float) -> None:
        value = self._validate_write_value(value)
        await self._writer.async_request(value)


# Load Balancing Limit


class LoadBalancingLimitNumber(BaseConfigNumber):
    coordinator: GrowattCoordinator
    _attr_translation_key = "load_balancing_limit"
    _attr_icon = "mdi:speedometer"
    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_min_value = 4
    _attr_native_max_value = 22
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "kW"
    _config_key = "G_ExternalLimitPower"

    def __init__(self, coordinator: GrowattCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "load_balancing_limit", device="meter")
        self._writer = ConfigurationWriter(
            coordinator, LoadBalancingLimitWritePolicy(self, self._config_key)
        )

    @property
    def native_value(self) -> float | None:
        value = self.coordinator.external_limit_power
        return int(value) if value is not None else 10

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.connected
            and control_is_applicable(
                ChargingControl.LOAD_BALANCING_LIMIT,
                self.coordinator.configuration_values,
            )
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return {
            **self.information_attributes,
            "ocpp_key": self._config_key,
        }

    def _validate_write_value(self, value: object) -> int | float:
        return _validated_entity_number(self, value, integer=True)

    async def async_set_native_value(self, value: float) -> None:
        value = self._validate_write_value(value)
        await self._writer.async_request(value)


# Electricity price


class ElectricityPriceNumber(BaseConfigNumber):
    coordinator: GrowattCoordinator
    _attr_translation_key = "electricity_price"
    _attr_icon = "mdi:cash"
    _attr_native_min_value = -2.0
    _attr_native_max_value = 2.0
    _attr_native_step = 0.01
    _attr_suggested_display_precision = 2
    _config_key = "G_TimeSharingPrice"

    def __init__(self, coordinator: GrowattCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "electricity_price")
        self._attr_native_unit_of_measurement = electricity_price_unit(coordinator.hass)
        self._writer = ConfigurationWriter(
            coordinator, ElectricityPriceWritePolicy(self, self._config_key)
        )

    @property
    def native_value(self) -> float | None:
        return self.coordinator.electricity_price

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        value = self.coordinator.configuration_values.get(self._config_key)
        return {
            "ocpp_key": self._config_key,
            "raw_value": value.raw_value if value is not None else None,
        }

    def _validate_write_value(self, value: object) -> int | float:
        return _validated_entity_number(self, value)

    async def async_set_native_value(self, value: float) -> None:
        value = self._validate_write_value(value)
        await self._writer.async_request(value)


@dataclass(frozen=True, kw_only=True)
class ConfigurationControlNumberDescription:
    """Declare one mode-aware number; the unique ID is ``<entry>_<key>_control``."""

    key: str
    control: ChargingControl
    icon: str
    native_min_value: float
    native_max_value: float
    native_step: float
    integer: bool = False
    native_unit_of_measurement: str | None = None
    device_class: Any = None
    suggested_display_precision: int | None = None
    device: Literal["charger", "meter"] = "charger"


CONTROL_NUMBERS = (
    # Configure the Modbus address of the external power meter.
    ConfigurationControlNumberDescription(
        key="power_meter_address",
        control=ChargingControl.POWER_METER_ADDRESS,
        icon="mdi:numeric",
        native_min_value=1,
        native_max_value=247,
        native_step=1,
        integer=True,
        device="meter",
    ),
    # Configure the grid power allowance used by PV Linkage.
    ConfigurationControlNumberDescription(
        key="solar_grid_import_limit",
        control=ChargingControl.SOLAR_GRID_IMPORT_LIMIT,
        icon="mdi:transmission-tower-import",
        native_min_value=0,
        native_max_value=22,
        native_step=0.1,
        native_unit_of_measurement="kW",
        device_class=NumberDeviceClass.POWER,
        suggested_display_precision=1,
    ),
)


class ConfigurationControlNumber(ThorEntity, NumberEntity):
    """Write one verified mode-aware number control."""

    coordinator: GrowattCoordinator

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: GrowattCoordinator,
        entry: ConfigEntry,
        description: ConfigurationControlNumberDescription,
    ) -> None:
        super().__init__(coordinator, entry, device=description.device)
        self._description = description
        self._configuration = ConfigurationControl(coordinator, description.control)
        self._attr_unique_id = f"{entry.entry_id}_{description.key}_control"
        self._attr_translation_key = description.key
        self._attr_icon = description.icon
        self._attr_native_min_value = description.native_min_value
        self._attr_native_max_value = description.native_max_value
        self._attr_native_step = description.native_step
        if description.native_unit_of_measurement is not None:
            self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        if description.device_class is not None:
            self._attr_device_class = description.device_class
        if description.suggested_display_precision is not None:
            self._attr_suggested_display_precision = description.suggested_display_precision

    @property
    def native_value(self) -> float | None:
        value = self._configuration.state
        if not isinstance(value, (int, float)):
            return None
        return int(value) if self._description.integer else float(value)

    @property
    def available(self) -> bool:
        return super().available and self._configuration.available and self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return self._configuration.attributes

    async def async_set_native_value(self, value: float) -> None:
        value = _validated_entity_number(self, value, integer=self._description.integer)
        raw_value = encode_control_value(self._description.control, value)
        await self._configuration.async_write(raw_value)


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

    def __init__(self, coordinator: GrowattCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "pv_smart_boost_target_energy")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.pv_draft.smart_target_energy_kwh

    @property
    def _write_block_reason(self) -> str | None:
        return self.coordinator.write_block_reason(ChargingControl.SOLAR_BOOST)

    @property
    def available(self) -> bool:
        # Keep a populated local draft visible even while applying it is unsafe.
        return (
            super().available
            and control_is_applicable(
                ChargingControl.SOLAR_BOOST,
                self.coordinator.configuration_values,
            )
            and self.coordinator.pv_draft.boost_mode == PvBoostMode.SMART
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.information_attributes

    async def async_set_native_value(self, value: float) -> None:
        value = _validated_entity_number(self, value)
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning(
                "Cannot edit Smart Boost target energy: %s",
                block_reason,
            )
            raise_write_blocked(block_reason)
        self.coordinator.update_pv_linkage_draft(smart_target_energy_kwh=value)
