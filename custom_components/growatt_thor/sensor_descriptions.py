"""Declarative HA sensor metadata and value projections."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.helpers.entity import EntityCategory

from .configuration.keys import (
    KEY_CHARGER_MODE,
    KEY_CHARGER_NET_DNS,
    KEY_CHARGER_NET_GATEWAY,
    KEY_CHARGER_NET_IP,
    KEY_CHARGER_NET_MAC,
    KEY_CHARGER_NET_MASK,
    KEY_EXTERNAL_SAMPLING_CUR_WRING,
    KEY_FULL_CONTINUE_CHARGE_ENABLE,
    KEY_NETWORK_MODE,
    KEY_OFF_PEAK_CURR,
    KEY_OFF_PEAK_ENABLE,
    KEY_OFF_PEAK_TIME,
    KEY_PEAK_VALLEY_ENABLE,
    KEY_POWER_METER_ADDR,
    KEY_POWER_METER_TYPE,
    KEY_RAND_DELAY_CHARGE_TIME,
    KEY_SOLAR_BOOST,
    KEY_SOLAR_LIMIT_POWER,
    KEY_SOLAR_MODE,
    KEY_SOLAR_THRESHOLD_CURR,
    KEY_WIFI_SSID,
    KEY_WORKING_MODE,
)
from .configuration.values import (
    CONFIGURATION_ENTITY_OPTIONS,
)
from .energy.currency import configured_currency, electricity_price_unit
from .entity import INFORMATION_ATTRIBUTES
from .ocpp.external_meter import EXTERNAL_METER_HEALTH_OPTIONS
from .sessions.constants import ACTIVE_POWER_THRESHOLD_W
from .sessions.display_times import session_time_zone
from .sessions.records import (
    SESSION_CHARGE_MODE_OPTIONS,
    SESSION_WORK_MODE_OPTIONS,
    normalize_session_charge_mode,
    normalize_session_work_mode,
)
from .timestamps import utc_timestamp

if TYPE_CHECKING:
    from .coordinator import GrowattCoordinator


SensorValue = str | float | int | None


@dataclass(frozen=True, kw_only=True)
class ThorSensorDescription(SensorEntityDescription):
    """Declare a sensor's state, availability, attributes and owning device."""

    value_fn: Callable[[GrowattCoordinator, str | None], SensorValue]
    available_fn: Callable[[GrowattCoordinator, str | None], bool] | None = None
    attrs_fn: Callable[[GrowattCoordinator, str | None], dict] | None = None
    unit_fn: Callable[[GrowattCoordinator], str] | None = None
    device: Literal["charger", "meter"] = "charger"
    coordinator_available: bool = True


def _external_meter_attributes(coordinator: GrowattCoordinator) -> dict:
    return {
        "vendor_used": coordinator.external_meter_used,
        "vendor_wring": coordinator.external_meter_wring,
        "last_updated_at": coordinator.external_meter_last_updated_at,
    }


@dataclass(frozen=True)
class GrowattConfigurationSensorDefinition:
    """Define a read-only Growatt configuration sensor."""

    entity_description: SensorEntityDescription
    configuration_key: str
    external_meter: bool = False
    has_information: bool = False


@dataclass(frozen=True)
class OcppBootSensorDefinition:
    """Define a diagnostic sensor sourced from BootNotification."""

    entity_description: SensorEntityDescription
    payload_key: str


OCPP_BOOT_SENSOR_DESCRIPTIONS = (
    OcppBootSensorDefinition(
        entity_description=SensorEntityDescription(
            key="charger_vendor",
            translation_key="charger_vendor",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:factory",
        ),
        payload_key="charge_point_vendor",
    ),
    OcppBootSensorDefinition(
        entity_description=SensorEntityDescription(
            key="charger_model",
            translation_key="charger_model",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:ev-station",
        ),
        payload_key="charge_point_model",
    ),
    OcppBootSensorDefinition(
        entity_description=SensorEntityDescription(
            key="firmware_version",
            translation_key="firmware_version",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:chip",
        ),
        payload_key="firmware_version",
    ),
    OcppBootSensorDefinition(
        entity_description=SensorEntityDescription(
            key="charger_serial_number",
            translation_key="charger_serial_number",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:identifier",
        ),
        payload_key="charge_point_serial_number",
    ),
)


CONFIGURATION_SENSOR_DESCRIPTIONS = (
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="working_mode",
            translation_key="working_mode",
            device_class=SensorDeviceClass.ENUM,
            options=list(CONFIGURATION_ENTITY_OPTIONS[KEY_WORKING_MODE]),
            icon="mdi:ev-station",
            entity_registry_enabled_default=False,
        ),
        configuration_key=KEY_WORKING_MODE,
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="charger_mode",
            translation_key="charger_mode",
            device_class=SensorDeviceClass.ENUM,
            options=list(CONFIGURATION_ENTITY_OPTIONS[KEY_CHARGER_MODE]),
            icon="mdi:shield-key-outline",
        ),
        configuration_key=KEY_CHARGER_MODE,
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="solar_mode",
            translation_key="solar_mode",
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.ENUM,
            options=list(CONFIGURATION_ENTITY_OPTIONS[KEY_SOLAR_MODE]),
            icon="mdi:solar-power",
            entity_registry_enabled_default=False,
        ),
        configuration_key=KEY_SOLAR_MODE,
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="solar_grid_import_limit",
            translation_key="solar_grid_import_limit",
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            icon="mdi:transmission-tower-import",
            entity_registry_enabled_default=False,
        ),
        configuration_key=KEY_SOLAR_LIMIT_POWER,
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="solar_boost",
            translation_key="solar_boost",
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.ENUM,
            options=list(CONFIGURATION_ENTITY_OPTIONS[KEY_SOLAR_BOOST]),
            icon="mdi:flash",
            entity_registry_enabled_default=False,
        ),
        configuration_key=KEY_SOLAR_BOOST,
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="solar_threshold_current",
            translation_key="solar_threshold_current",
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.CURRENT,
            native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
            icon="mdi:current-ac",
        ),
        configuration_key=KEY_SOLAR_THRESHOLD_CURR,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="grid_off_peak_charging",
            translation_key="grid_off_peak_charging",
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.ENUM,
            options=list(CONFIGURATION_ENTITY_OPTIONS[KEY_PEAK_VALLEY_ENABLE]),
            icon="mdi:transmission-tower",
        ),
        configuration_key=KEY_PEAK_VALLEY_ENABLE,
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="off_peak_enable_setting",
            translation_key="off_peak_enable_setting",
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.ENUM,
            options=list(CONFIGURATION_ENTITY_OPTIONS[KEY_OFF_PEAK_ENABLE]),
            icon="mdi:clock-check-outline",
            entity_registry_enabled_default=False,
        ),
        configuration_key=KEY_OFF_PEAK_ENABLE,
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="off_peak_schedule",
            translation_key="off_peak_schedule",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:calendar-clock",
        ),
        configuration_key=KEY_OFF_PEAK_TIME,
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="off_peak_current",
            translation_key="off_peak_current",
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.CURRENT,
            native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
            icon="mdi:current-ac",
        ),
        configuration_key=KEY_OFF_PEAK_CURR,
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="power_meter_type",
            translation_key="power_meter_type",
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.ENUM,
            options=list(CONFIGURATION_ENTITY_OPTIONS[KEY_POWER_METER_TYPE]),
            icon="mdi:counter",
            entity_registry_enabled_default=False,
        ),
        configuration_key=KEY_POWER_METER_TYPE,
        external_meter=True,
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="power_meter_address",
            translation_key="power_meter_address",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:numeric",
            entity_registry_enabled_default=False,
        ),
        configuration_key=KEY_POWER_METER_ADDR,
        external_meter=True,
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="external_sampling_wiring",
            translation_key="reported_external_sampling_method",
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.ENUM,
            options=list(CONFIGURATION_ENTITY_OPTIONS[KEY_EXTERNAL_SAMPLING_CUR_WRING]),
            icon="mdi:connection",
            entity_registry_enabled_default=False,
        ),
        configuration_key=KEY_EXTERNAL_SAMPLING_CUR_WRING,
        external_meter=True,
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="warm_up_after_full_charge",
            translation_key="warm_up_after_full_charge",
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.ENUM,
            options=list(CONFIGURATION_ENTITY_OPTIONS[KEY_FULL_CONTINUE_CHARGE_ENABLE]),
            icon="mdi:car-defrost-front",
            entity_registry_enabled_default=False,
        ),
        configuration_key=KEY_FULL_CONTINUE_CHARGE_ENABLE,
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="delayed_charging_time",
            translation_key="delayed_charging_time",
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.SECONDS,
            icon="mdi:timer-sand",
        ),
        configuration_key=KEY_RAND_DELAY_CHARGE_TIME,
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="network_mode",
            translation_key="network_mode",
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.ENUM,
            options=list(CONFIGURATION_ENTITY_OPTIONS[KEY_NETWORK_MODE]),
            icon="mdi:network",
        ),
        configuration_key=KEY_NETWORK_MODE,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="network_ip_address",
            translation_key="network_ip_address",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:ip-network",
        ),
        configuration_key=KEY_CHARGER_NET_IP,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="network_subnet_mask",
            translation_key="network_subnet_mask",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:ip-network-outline",
        ),
        configuration_key=KEY_CHARGER_NET_MASK,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="network_gateway",
            translation_key="network_gateway",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:router-network",
        ),
        configuration_key=KEY_CHARGER_NET_GATEWAY,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="network_dns_server",
            translation_key="network_dns_server",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:dns",
        ),
        configuration_key=KEY_CHARGER_NET_DNS,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="network_mac_address",
            translation_key="network_mac_address",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:network-outline",
        ),
        configuration_key=KEY_CHARGER_NET_MAC,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="network_wifi_ssid",
            translation_key="network_wifi_ssid",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:wifi",
        ),
        configuration_key=KEY_WIFI_SSID,
    ),
)


def _energy_charged_value(coordinator: GrowattCoordinator, phase: str | None) -> SensorValue:
    # Unknown until the charger reports a value after start-up or a
    # reload. Reporting 0 here would look like a meter reset to this
    # total_increasing sensor, so the next sample of a running session
    # would be counted twice by long-term statistics and utility meters.
    if coordinator.energy is None:
        return None
    return round(coordinator.energy / 1000, 3)


def _electricity_price_value(coordinator: GrowattCoordinator, phase: str | None) -> SensorValue:
    value = coordinator.electricity_price
    return round(value, 2) if value is not None else None


def _last_session_duration_value(coordinator: GrowattCoordinator, phase: str | None) -> SensorValue:
    minutes = coordinator.last_session_duration_minutes
    return round(minutes / 60, 2) if minutes is not None else None


def _last_session_effective_charging_duration_value(
    coordinator: GrowattCoordinator, phase: str | None
) -> SensorValue:
    minutes = coordinator.last_session_effective_charging_minutes
    return round(minutes / 60, 2) if minutes is not None else None


def _last_session_effective_charging_duration_attributes(
    coordinator: GrowattCoordinator, phase: str | None
) -> dict:
    return {
        **INFORMATION_ATTRIBUTES,
        "calculation_method": "ocpp_meter_values",
        "active_power_threshold_w": ACTIVE_POWER_THRESHOLD_W,
    }


def _last_session_charge_mode_value(
    coordinator: GrowattCoordinator, phase: str | None
) -> SensorValue:
    return normalize_session_charge_mode(coordinator.last_session_charge_mode)


def _last_session_charge_mode_attributes(
    coordinator: GrowattCoordinator, phase: str | None
) -> dict:
    return {"raw_value": coordinator.last_session_charge_mode}


def _last_session_work_mode_value(
    coordinator: GrowattCoordinator, phase: str | None
) -> SensorValue:
    return normalize_session_work_mode(coordinator.last_session_work_mode)


def _last_session_work_mode_attributes(coordinator: GrowattCoordinator, phase: str | None) -> dict:
    return {"raw_value": coordinator.last_session_work_mode}


def _current_value(coordinator: GrowattCoordinator, phase: str | None) -> SensorValue:
    value = coordinator.currents.get(phase)
    return value if value is not None else 0


def _voltage_value(coordinator: GrowattCoordinator, phase: str | None) -> SensorValue:
    value = coordinator.voltages.get(phase)
    return value if value is not None else 0


def _phase_power_value(coordinator: GrowattCoordinator, phase: str | None) -> SensorValue:
    value = coordinator.phase_power.get(phase)
    return value if value is not None else 0


def _external_meter_health_attributes(coordinator: GrowattCoordinator, phase: str | None) -> dict:
    return {
        **_external_meter_attributes(coordinator),
        **INFORMATION_ATTRIBUTES,
        "connector_id": coordinator.external_meter_fault_connector_id,
        "error_code": coordinator.external_meter_fault_error_code,
        "info": coordinator.external_meter_fault_info,
        "consecutive_timeouts": coordinator.meterval_consecutive_timeouts,
    }


def _grid_voltage_value(coordinator: GrowattCoordinator, phase: str | None) -> SensorValue:
    return coordinator.grid_voltages.get(phase)


def _grid_current_value(coordinator: GrowattCoordinator, phase: str | None) -> SensorValue:
    return coordinator.grid_currents.get(phase)


SENSOR_DESCRIPTIONS = {
    "ServerUrlSensor": ThorSensorDescription(
        key="server_url",
        value_fn=lambda coordinator, phase: coordinator.server_url,
        translation_key="server_url",
        icon="mdi:server",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "ChargePointIdSensor": ThorSensorDescription(
        key="charge_point_id",
        value_fn=lambda coordinator, phase: coordinator.charge_point_id,
        translation_key="charge_point_id",
        icon="mdi:identifier",
        entity_category=EntityCategory.DIAGNOSTIC,
        coordinator_available=False,
        available_fn=lambda coordinator, phase: coordinator.charge_point_id is not None,
    ),
    "ChargingPowerSensor": ThorSensorDescription(
        key="charging_power",
        value_fn=lambda coordinator, phase: (
            coordinator.power if coordinator.power is not None else 0
        ),
        translation_key="charging_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    "EnergyChargedSensor": ThorSensorDescription(
        key="energy_charged",
        value_fn=_energy_charged_value,
        translation_key="energy_charged",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    "TotalEnergyChargedSensor": ThorSensorDescription(
        key="total_energy_charged",
        value_fn=lambda coordinator, phase: round(coordinator.total_energy_charged, 3),
        translation_key="total_energy_charged",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    "ElectricityPriceSensor": ThorSensorDescription(
        key="electricity_price",
        value_fn=_electricity_price_value,
        translation_key="electricity_price",
        icon="mdi:cash",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        unit_fn=lambda coordinator: electricity_price_unit(coordinator.hass),
    ),
    "LastSessionEnergySensor": ThorSensorDescription(
        key="last_session_energy",
        value_fn=lambda coordinator, phase: (
            round(coordinator.last_session_energy, 3)
            if coordinator.last_session_energy is not None
            else None
        ),
        translation_key="last_session_energy",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    "LastSessionCostSensor": ThorSensorDescription(
        key="last_session_cost",
        value_fn=lambda coordinator, phase: (
            round(coordinator.last_session_cost, 2)
            if coordinator.last_session_cost is not None
            else None
        ),
        translation_key="last_session_cost",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash",
        unit_fn=lambda coordinator: configured_currency(coordinator.hass),
    ),
    "LastSessionDurationSensor": ThorSensorDescription(
        key="last_session_duration",
        value_fn=_last_session_duration_value,
        translation_key="last_session_duration",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=2,
        icon="mdi:timer-outline",
    ),
    "LastSessionEffectiveChargingDurationSensor": ThorSensorDescription(
        key="last_session_effective_charging_duration",
        value_fn=_last_session_effective_charging_duration_value,
        translation_key="last_session_effective_charging_duration",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=2,
        icon="mdi:ev-plug-type2",
        attrs_fn=_last_session_effective_charging_duration_attributes,
    ),
    "LastSessionStartSensor": ThorSensorDescription(
        key="last_session_start",
        value_fn=lambda coordinator, phase: utc_timestamp(
            coordinator.last_session_start, session_time_zone(coordinator)
        ),
        translation_key="last_session_start",
        icon="mdi:clock-start",
    ),
    "LastSessionEndSensor": ThorSensorDescription(
        key="last_session_end",
        value_fn=lambda coordinator, phase: utc_timestamp(
            coordinator.last_session_end, session_time_zone(coordinator)
        ),
        translation_key="last_session_end",
        icon="mdi:clock-end",
    ),
    "LastSessionPlugTimeSensor": ThorSensorDescription(
        key="last_session_plug_time",
        value_fn=lambda coordinator, phase: utc_timestamp(
            coordinator.last_session_plug_time, session_time_zone(coordinator)
        ),
        translation_key="last_session_plug_time",
        icon="mdi:power-plug",
    ),
    "LastSessionUnplugTimeSensor": ThorSensorDescription(
        key="last_session_unplug_time",
        value_fn=lambda coordinator, phase: utc_timestamp(
            coordinator.last_session_unplug_time, session_time_zone(coordinator)
        ),
        translation_key="last_session_unplug_time",
        icon="mdi:power-plug-off",
    ),
    "LastSessionTransactionIdSensor": ThorSensorDescription(
        key="last_session_transaction_id",
        value_fn=lambda coordinator, phase: coordinator.last_session_transaction_id,
        translation_key="last_session_transaction_id",
        icon="mdi:identifier",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "LastSessionChargeModeSensor": ThorSensorDescription(
        key="last_session_charge_mode",
        value_fn=_last_session_charge_mode_value,
        translation_key="last_session_charge_mode",
        device_class=SensorDeviceClass.ENUM,
        options=list(SESSION_CHARGE_MODE_OPTIONS),
        icon="mdi:shield-key-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        available_fn=lambda coordinator, phase: (
            _last_session_charge_mode_value(coordinator, phase) is not None
        ),
        attrs_fn=_last_session_charge_mode_attributes,
    ),
    "LastSessionWorkModeSensor": ThorSensorDescription(
        key="last_session_work_mode",
        value_fn=_last_session_work_mode_value,
        translation_key="last_session_work_mode",
        device_class=SensorDeviceClass.ENUM,
        options=list(SESSION_WORK_MODE_OPTIONS),
        icon="mdi:ev-station",
        entity_category=EntityCategory.DIAGNOSTIC,
        available_fn=lambda coordinator, phase: (
            _last_session_work_mode_value(coordinator, phase) is not None
        ),
        attrs_fn=_last_session_work_mode_attributes,
    ),
    "CurrentSensor": ThorSensorDescription(
        key="current",
        value_fn=_current_value,
        translation_key="current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
    ),
    "VoltageSensor": ThorSensorDescription(
        key="voltage",
        value_fn=_voltage_value,
        translation_key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
    ),
    "PhasePowerSensor": ThorSensorDescription(
        key="power",
        value_fn=_phase_power_value,
        translation_key="phase_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    "TemperatureSensor": ThorSensorDescription(
        key="temperature",
        value_fn=lambda coordinator, phase: coordinator.temperature,
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        available_fn=lambda coordinator, phase: coordinator.temperature is not None,
    ),
    "ExternalMeterHealthSensor": ThorSensorDescription(
        key="health",
        value_fn=lambda coordinator, phase: coordinator.external_meter_health,
        translation_key="external_meter_health",
        device_class=SensorDeviceClass.ENUM,
        options=list(EXTERNAL_METER_HEALTH_OPTIONS),
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:meter-electric-outline",
        device="meter",
        available_fn=lambda coordinator, phase: coordinator.connected,
        attrs_fn=_external_meter_health_attributes,
    ),
    "GridPowerSensor": ThorSensorDescription(
        key="power",
        value_fn=lambda coordinator, phase: coordinator.grid_power,
        translation_key="grid_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:transmission-tower",
        native_unit_of_measurement=UnitOfPower.WATT,
        device="meter",
        available_fn=lambda coordinator, phase: (
            coordinator.connected and (coordinator.grid_power is not None)
        ),
    ),
    "GridVoltageSensor": ThorSensorDescription(
        key="voltage",
        value_fn=_grid_voltage_value,
        translation_key="grid_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:current-ac",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device="meter",
        available_fn=lambda coordinator, phase: (
            coordinator.connected and (_grid_voltage_value(coordinator, phase) is not None)
        ),
    ),
    "GridCurrentSensor": ThorSensorDescription(
        key="current",
        value_fn=_grid_current_value,
        translation_key="grid_current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:current-dc",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device="meter",
        available_fn=lambda coordinator, phase: (
            coordinator.connected and (_grid_current_value(coordinator, phase) is not None)
        ),
    ),
}
