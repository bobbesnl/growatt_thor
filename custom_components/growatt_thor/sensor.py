from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    UnitOfEnergy,
)
from homeassistant.helpers.entity import EntityCategory

from .charging.faults import CHARGER_FAULT_OPTIONS
from .charging.snapshot import charger_snapshot
from .configuration.values import (
    ConfigurationValue,
    configuration_entity_state,
)
from .energy.currency import configured_currency
from .energy.options import CONF_SITE_PROFILE
from .energy.site_inputs import coverage_percent
from .entity import ThorEntity
from .ocpp.core.diagnostics import boot_notification_field
from .ocpp.core.status import OCPP_STATUS_OPTIONS
from .presentation.entity_map import card_payload
from .runtime.write_results import COMMAND_COMPLETION_STATUSES
from .sensor_descriptions import (
    CONFIGURATION_SENSOR_DESCRIPTIONS,
    OCPP_BOOT_SENSOR_DESCRIPTIONS,
    SENSOR_DESCRIPTIONS,
    SensorValue,
    ThorSensorDescription,
    _external_meter_attributes,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import GrowattCoordinator
    from .runtime.entry import ThorConfigEntry
    from .sensor_descriptions import GrowattConfigurationSensorDefinition, OcppBootSensorDefinition


async def async_setup_entry(
    hass: HomeAssistant, entry: ThorConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    # HA forwards platforms only after this entry has claimed its coordinator.
    coordinator = cast("GrowattCoordinator", entry.runtime_data.coordinator)
    boot_sensors = [
        OcppBootSensor(coordinator, entry, description)
        for description in OCPP_BOOT_SENSOR_DESCRIPTIONS
    ]
    configuration_sensors = [
        GrowattConfigurationSensor(coordinator, entry, description)
        for description in CONFIGURATION_SENSOR_DESCRIPTIONS
    ]
    site_sensors = (
        [
            SiteAccountingSensor(coordinator, entry, key)
            for key in (
                "energy_kwh",
                "direct_solar_kwh",
                "direct_grid_kwh",
                "battery_unknown_kwh",
                "unknown_kwh",
                "effective_grid_cost",
                "coverage",
            )
        ]
        if entry.data.get(CONF_SITE_PROFILE, "disabled") != "disabled"
        else []
    )

    def described(name: str, phase: str | None = None) -> ThorSensor:
        return described_sensor(coordinator, entry, SENSOR_DESCRIPTIONS[name], phase)

    async_add_entities(
        [
            #  Status / live
            StatusSensor(coordinator, entry),
            LastChargerFaultSensor(coordinator, entry),
            LastCommandResultSensor(coordinator, entry),
            described("ChargePointIdSensor"),
            *boot_sensors,
            described("ChargingPowerSensor"),
            described("EnergyChargedSensor"),
            described("ServerUrlSensor"),
            #  Last session
            described("LastSessionEnergySensor"),
            described("LastSessionCostSensor"),
            described("LastSessionStartSensor"),
            described("LastSessionEndSensor"),
            described("LastSessionPlugTimeSensor"),
            described("LastSessionUnplugTimeSensor"),
            described("LastSessionDurationSensor"),
            described("LastSessionEffectiveChargingDurationSensor"),
            described("LastSessionTransactionIdSensor"),
            described("LastSessionChargeModeSensor"),
            described("LastSessionWorkModeSensor"),
            #  Persistent cumulative total (Energy Dashboard)
            described("TotalEnergyChargedSensor"),
            *site_sensors,
            #  Per-phase charging diagnostics
            described("CurrentSensor", "L1"),
            described("CurrentSensor", "L2"),
            described("CurrentSensor", "L3"),
            described("VoltageSensor", "L1"),
            described("VoltageSensor", "L2"),
            described("VoltageSensor", "L3"),
            described("PhasePowerSensor", "L1"),
            described("PhasePowerSensor", "L2"),
            described("PhasePowerSensor", "L3"),
            described("TemperatureSensor"),
            #  Load Balancing Grid sensors
            described("ExternalMeterHealthSensor"),
            described("GridPowerSensor"),
            described("GridVoltageSensor", "L1"),
            described("GridVoltageSensor", "L2"),
            described("GridVoltageSensor", "L3"),
            described("GridCurrentSensor", "L1"),
            described("GridCurrentSensor", "L2"),
            described("GridCurrentSensor", "L3"),
            #  Electricity tariff
            described("ElectricityPriceSensor"),
            #  Read-only Growatt configuration
            *configuration_sensors,
        ]
    )


# Base for charger sensors (EV Charger device)


class BaseSensor(ThorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: GrowattCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{key}"


class SiteAccountingSensor(BaseSensor):
    """Cumulative observed accounting since this feature was enabled."""

    def __init__(self, coordinator: GrowattCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator, entry, f"site_{key}")
        self.key = key
        self._attr_translation_key = f"site_{key}"
        self._attr_device_class = (
            SensorDeviceClass.MONETARY
            if key == "effective_grid_cost"
            else SensorDeviceClass.ENERGY
            if key != "coverage"
            else None
        )
        self._attr_state_class = (
            SensorStateClass.TOTAL
            if key == "effective_grid_cost"
            else SensorStateClass.MEASUREMENT
            if key == "coverage"
            else SensorStateClass.TOTAL_INCREASING
        )
        if key in ("battery_unknown_kwh", "unknown_kwh"):
            self._attr_entity_registry_enabled_default = False
        self._attr_native_unit_of_measurement = (
            configured_currency(coordinator.hass)
            if key == "effective_grid_cost"
            else "%"
            if key == "coverage"
            else UnitOfEnergy.KILO_WATT_HOUR
        )

    @property
    def native_value(self) -> str | float | int | None:
        if self.key == "coverage":
            return coverage_percent(self.coordinator.site_accounting_totals)
        return round(self.coordinator.site_accounting_totals[self.key], 6)


class LastChargerFaultSensor(BaseSensor):
    """Expose the most recently retained charger fault."""

    _attr_translation_key = "last_charger_fault"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(CHARGER_FAULT_OPTIONS)
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:alert-octagon-outline"

    def __init__(self, coordinator: GrowattCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "last_charger_fault")

    @property
    def native_value(self) -> str | float | int | None:
        fault = self.coordinator.last_charger_fault
        return fault.category if fault is not None else None

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.last_charger_fault is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        fault = self.coordinator.last_charger_fault
        if fault is None:
            return self.information_attributes
        return {
            **self.information_attributes,
            **fault.as_dict(),
        }


class LastCommandResultSensor(BaseSensor):
    """Expose the latest queue completion for automation correlation."""

    _attr_translation_key = "last_command_result"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(COMMAND_COMPLETION_STATUSES)
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:progress-check"

    def __init__(self, coordinator: GrowattCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "last_command_result")

    @property
    def native_value(self) -> str | float | int | None:
        result = self.coordinator.last_command_result
        return result.status.value if result is not None else None

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.last_command_result is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        result = self.coordinator.last_command_result
        if result is None:
            return self.information_attributes
        attributes = result.as_dict()
        attributes.pop("status")
        return {
            **self.information_attributes,
            **attributes,
        }


# Base for external meter sensors


# Read-only retained configuration


class GrowattConfigurationSensor(ThorEntity, SensorEntity):
    """Expose one retained Growatt configuration value."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GrowattCoordinator,
        entry: ConfigEntry,
        definition: GrowattConfigurationSensorDefinition,
    ) -> None:
        super().__init__(
            coordinator, entry, device="meter" if definition.external_meter else "charger"
        )
        self.entity_description = definition.entity_description
        self._configuration_key = definition.configuration_key
        self._has_information = definition.has_information

        if definition.external_meter:
            self._attr_unique_id = f"{entry.entry_id}_external_meter_{self.entity_description.key}"
        else:
            self._attr_unique_id = f"{entry.entry_id}_{self.entity_description.key}"

    @property
    def _configuration_value(self) -> ConfigurationValue | None:
        return self.coordinator.configuration_values.get(self._configuration_key)

    @property
    def native_value(self) -> str | float | int | None:
        return configuration_entity_state(
            self._configuration_key,
            self._configuration_value,
        )

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        value = self._configuration_value
        if value is None:
            return None
        attributes = {
            "ocpp_key": value.key,
            "raw_value": value.raw_value,
            "readonly": value.readonly,
        }
        if self._has_information:
            attributes.update(self.information_attributes)
        return attributes


# Retained OCPP BootNotification metadata


class OcppBootSensor(BaseSensor):
    """Expose one retained BootNotification field."""

    def __init__(
        self,
        coordinator: GrowattCoordinator,
        entry: ConfigEntry,
        definition: OcppBootSensorDefinition,
    ) -> None:
        super().__init__(coordinator, entry, definition.entity_description.key)
        self.entity_description = definition.entity_description
        self._payload_key = definition.payload_key

    @property
    def native_value(self) -> str | float | int | None:
        return boot_notification_field(
            self.coordinator.boot_notification,
            self._payload_key,
        )

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None


# Status (MAIN SENSOR - EV Charger)


class StatusSensor(BaseSensor):
    # The card projection and connection activity change on most OCPP frames.
    # Keep them live without storing a fresh large attribute blob each time.
    _unrecorded_attributes = frozenset(
        {
            "thor_card",
            "last_message_at",
            "last_heartbeat_at",
            "last_message_action",
            "connection_started_at",
        }
    )
    _attr_translation_key = "status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = (*OCPP_STATUS_OPTIONS, "offline")
    _attr_icon = "mdi:ev-station"

    def __init__(self, coordinator: GrowattCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "status")

    @property
    def native_value(self) -> str | float | int | None:
        snapshot = charger_snapshot(self.coordinator)
        return snapshot.status if snapshot.connected else "offline"

    @property
    def available(self) -> bool:
        # This entity also carries retained history and the card contract.
        # HA omits extra_state_attributes on unavailable entities, so transport
        # loss must be represented as an explicit state instead.
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "connected": charger_snapshot(self.coordinator).connected,
            "connection_started_at": self.coordinator.connection_started_at,
            "last_message_at": self.coordinator.last_message_at,
            "last_message_action": self.coordinator.last_message_action,
            "last_heartbeat_at": self.coordinator.last_heartbeat_at,
            "thor_card": self._dashboard_attributes(),
        }

    def _dashboard_attributes(self) -> dict[str, Any]:
        # The card prefers the WebSocket subscription with the same payload;
        # the attribute stays as its fallback.
        return card_payload(self.hass, self.coordinator)


class ThorSensor(ThorEntity, SensorEntity):
    """Project one description into HA while preserving its explicit boundaries."""

    entity_description: ThorSensorDescription
    phase: str | None = None

    def __init__(
        self,
        coordinator: GrowattCoordinator,
        entry: ConfigEntry,
        description: ThorSensorDescription,
        phase: str | None = None,
    ) -> None:
        self.entity_description = description
        super().__init__(coordinator, entry, device=description.device)
        self.phase = phase
        prefix = "load_balancing_" if description.device == "meter" else ""
        suffix = description.key + (f"_{phase.lower()}" if phase is not None else "")
        self._attr_unique_id = f"{entry.entry_id}_{prefix}{suffix}"
        if phase is not None:
            self._attr_translation_placeholders = {"phase": phase}
        if description.unit_fn is not None:
            self._attr_native_unit_of_measurement = description.unit_fn(coordinator)

    @property
    def native_value(self) -> SensorValue:
        return self.entity_description.value_fn(self.coordinator, self.phase)

    @property
    def available(self) -> bool:
        description = self.entity_description
        if description.coordinator_available and not super().available:
            return False
        return (
            description.available_fn(self.coordinator, self.phase)
            if description.available_fn
            else True
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        description = self.entity_description
        if description.attrs_fn is not None:
            return description.attrs_fn(self.coordinator, self.phase)
        return (
            _external_meter_attributes(self.coordinator) if description.device == "meter" else None
        )


class ThorMeterSensor(ThorSensor):
    _unrecorded_attributes = frozenset({"last_updated_at"})


def described_sensor(
    coordinator: GrowattCoordinator,
    entry: ConfigEntry,
    description: ThorSensorDescription,
    phase: str | None = None,
) -> ThorSensor:
    """Build the entity class matching a description's device.

    Home Assistant combines ``_unrecorded_attributes`` per class, so external
    meter sensors need their own class to exclude ``last_updated_at``.
    """
    entity_class = ThorMeterSensor if description.device == "meter" else ThorSensor
    return entity_class(coordinator, entry, description, phase)
