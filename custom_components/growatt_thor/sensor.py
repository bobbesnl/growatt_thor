from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.const import (
    UnitOfPower,
    UnitOfEnergy,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfTemperature,
    UnitOfTime,
)

from .configuration import (
    CONFIGURATION_ENTITY_OPTIONS,
    configuration_entity_state,
)
from .charger_faults import CHARGER_FAULT_OPTIONS
from .const import DOMAIN
from .currency import configured_currency, electricity_price_unit
from .external_meter import EXTERNAL_METER_HEALTH_OPTIONS
from .ocpp_diagnostics import boot_notification_field
from .ocpp_status import OCPP_STATUS_OPTIONS, normalize_ocpp_status
from .session_records import (
    SESSION_CHARGE_MODE_OPTIONS,
    SESSION_WORK_MODE_OPTIONS,
    normalize_session_charge_mode,
    normalize_session_work_mode,
)


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
            options=list(CONFIGURATION_ENTITY_OPTIONS["G_WorkingMode"]),
            icon="mdi:ev-station",
            entity_registry_enabled_default=False,
        ),
        configuration_key="G_WorkingMode",
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="charger_mode",
            translation_key="charger_mode",
            device_class=SensorDeviceClass.ENUM,
            options=list(CONFIGURATION_ENTITY_OPTIONS["G_ChargerMode"]),
            icon="mdi:shield-key-outline",
        ),
        configuration_key="G_ChargerMode",
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="solar_mode",
            translation_key="solar_mode",
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.ENUM,
            options=list(CONFIGURATION_ENTITY_OPTIONS["G_SolarMode"]),
            icon="mdi:solar-power",
            entity_registry_enabled_default=False,
        ),
        configuration_key="G_SolarMode",
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
        configuration_key="G_SolarLimitPower",
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="solar_boost",
            translation_key="solar_boost",
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.ENUM,
            options=list(CONFIGURATION_ENTITY_OPTIONS["G_SolarBoost"]),
            icon="mdi:flash",
            entity_registry_enabled_default=False,
        ),
        configuration_key="G_SolarBoost",
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
        configuration_key="G_SolarThresholdCurr",
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="grid_off_peak_charging",
            translation_key="grid_off_peak_charging",
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.ENUM,
            options=list(CONFIGURATION_ENTITY_OPTIONS["G_PeakValleyEnable"]),
            icon="mdi:transmission-tower",
        ),
        configuration_key="G_PeakValleyEnable",
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="off_peak_enable_setting",
            translation_key="off_peak_enable_setting",
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.ENUM,
            options=list(CONFIGURATION_ENTITY_OPTIONS["G_OffPeakEnable"]),
            icon="mdi:clock-check-outline",
            entity_registry_enabled_default=False,
        ),
        configuration_key="G_OffPeakEnable",
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="off_peak_schedule",
            translation_key="off_peak_schedule",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:calendar-clock",
        ),
        configuration_key="G_OffPeakTime",
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
        configuration_key="G_OffPeakCurr",
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="power_meter_type",
            translation_key="power_meter_type",
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.ENUM,
            options=list(CONFIGURATION_ENTITY_OPTIONS["G_PowerMeterType"]),
            icon="mdi:counter",
            entity_registry_enabled_default=False,
        ),
        configuration_key="G_PowerMeterType",
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
        configuration_key="G_PowerMeterAddr",
        external_meter=True,
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="external_sampling_wiring",
            translation_key="reported_external_sampling_method",
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.ENUM,
            options=list(
                CONFIGURATION_ENTITY_OPTIONS["G_ExternalSamplingCurWring"]
            ),
            icon="mdi:connection",
            entity_registry_enabled_default=False,
        ),
        configuration_key="G_ExternalSamplingCurWring",
        external_meter=True,
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="warm_up_after_full_charge",
            translation_key="warm_up_after_full_charge",
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.ENUM,
            options=list(
                CONFIGURATION_ENTITY_OPTIONS["G_FullContinueChargeEnable"]
            ),
            icon="mdi:car-defrost-front",
            entity_registry_enabled_default=False,
        ),
        configuration_key="G_FullContinueChargeEnable",
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
        configuration_key="G_RandDelayChargeTime",
        has_information=True,
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="network_mode",
            translation_key="network_mode",
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.ENUM,
            options=list(CONFIGURATION_ENTITY_OPTIONS["G_NetworkMode"]),
            icon="mdi:network",
        ),
        configuration_key="G_NetworkMode",
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="network_ip_address",
            translation_key="network_ip_address",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:ip-network",
        ),
        configuration_key="G_ChargerNetIP",
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="network_subnet_mask",
            translation_key="network_subnet_mask",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:ip-network-outline",
        ),
        configuration_key="G_ChargerNetMask",
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="network_gateway",
            translation_key="network_gateway",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:router-network",
        ),
        configuration_key="G_ChargerNetGateway",
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="network_dns_server",
            translation_key="network_dns_server",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:dns",
        ),
        configuration_key="G_ChargerNetDNS",
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="network_mac_address",
            translation_key="network_mac_address",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:network-outline",
        ),
        configuration_key="G_ChargerNetMac",
    ),
    GrowattConfigurationSensorDefinition(
        entity_description=SensorEntityDescription(
            key="network_wifi_ssid",
            translation_key="network_wifi_ssid",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:wifi",
        ),
        configuration_key="G_WifiSSID",
    ),
)

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN]["coordinator"]
    boot_sensors = [
        OcppBootSensor(coordinator, entry, description)
        for description in OCPP_BOOT_SENSOR_DESCRIPTIONS
    ]
    configuration_sensors = [
        GrowattConfigurationSensor(coordinator, entry, description)
        for description in CONFIGURATION_SENSOR_DESCRIPTIONS
    ]

    async_add_entities(
        [
            # ── Status / live ─────────────────────────
            StatusSensor(coordinator, entry),
            LastChargerFaultSensor(coordinator, entry),
            ChargePointIdSensor(coordinator, entry),
            *boot_sensors,
            ChargingPowerSensor(coordinator, entry),
            EnergyChargedSensor(coordinator, entry),
            ServerUrlSensor(coordinator, entry),

            # ── Laatste sessie ────────────────────────
            LastSessionEnergySensor(coordinator, entry),
            LastSessionCostSensor(coordinator, entry),
            LastSessionStartSensor(coordinator, entry),
            LastSessionEndSensor(coordinator, entry),
            LastSessionPlugTimeSensor(coordinator, entry),
            LastSessionUnplugTimeSensor(coordinator, entry),
            LastSessionDurationSensor(coordinator, entry),
            LastSessionEffectiveChargingDurationSensor(coordinator, entry),
            LastSessionTransactionIdSensor(coordinator, entry),
            LastSessionChargeModeSensor(coordinator, entry),
            LastSessionWorkModeSensor(coordinator, entry),

            # ── Cumulatief totaal (Energy Dashboard) ──
            TotalEnergyChargedSensor(coordinator, entry),

            # ── Fase-specifiek (diagnostics tijdens laden) ──
            CurrentSensor(coordinator, entry, "L1"),
            CurrentSensor(coordinator, entry, "L2"),
            CurrentSensor(coordinator, entry, "L3"),

            VoltageSensor(coordinator, entry, "L1"),
            VoltageSensor(coordinator, entry, "L2"),
            VoltageSensor(coordinator, entry, "L3"),

            PhasePowerSensor(coordinator, entry, "L1"),
            PhasePowerSensor(coordinator, entry, "L2"),
            PhasePowerSensor(coordinator, entry, "L3"),

            TemperatureSensor(coordinator, entry),

            # ── Load Balancing Grid sensors ───────────
            ExternalMeterHealthSensor(coordinator, entry),
            GridPowerSensor(coordinator, entry),
            GridVoltageSensor(coordinator, entry, "L1"),
            GridVoltageSensor(coordinator, entry, "L2"),
            GridVoltageSensor(coordinator, entry, "L3"),
            GridCurrentSensor(coordinator, entry, "L1"),
            GridCurrentSensor(coordinator, entry, "L2"),
            GridCurrentSensor(coordinator, entry, "L3"),

            # ── Elektricteitstarief ───────────────────
            ElectricityPriceSensor(coordinator, entry),

            # ── Read-only Growatt configuration ──────
            *configuration_sensors,
        ]
    )


# ─────────────────────────────
# Base voor charger sensors (EV Charger device)
# ─────────────────────────────

class BaseSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, key):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }


class LastChargerFaultSensor(BaseSensor):
    """Expose the most recently retained charger fault."""

    _attr_translation_key = "last_charger_fault"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(CHARGER_FAULT_OPTIONS)
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:alert-octagon-outline"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_charger_fault")

    @property
    def native_value(self):
        fault = self.coordinator.last_charger_fault
        return fault.category if fault is not None else None

    @property
    def available(self):
        return super().available and self.coordinator.last_charger_fault is not None

    @property
    def extra_state_attributes(self):
        fault = self.coordinator.last_charger_fault
        if fault is None:
            return {"information": "details"}
        return {
            "information": "details",
            **fault.as_dict(),
        }


# ─────────────────────────────
# Base for external meter sensors
# ─────────────────────────────

class BaseExternalMeterSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, key):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_load_balancing_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id, "grid_connection")},
            "name": "Growatt THOR External Meter",
            "manufacturer": "Growatt",
            "model": "THOR External Meter",
        }

    @property
    def extra_state_attributes(self):
        return {
            "vendor_used": self.coordinator.external_meter_used,
            "vendor_wring": self.coordinator.external_meter_wring,
            "last_updated_at": self.coordinator.external_meter_last_updated_at,
        }


# ─────────────────────────────
# Read-only retained configuration
# ─────────────────────────────

class GrowattConfigurationSensor(CoordinatorEntity, SensorEntity):
    """Expose one retained Growatt configuration value."""

    _attr_has_entity_name = True
    def __init__(self, coordinator, entry, definition):
        super().__init__(coordinator)
        self.entity_description = definition.entity_description
        self._configuration_key = definition.configuration_key
        self._has_information = definition.has_information

        if definition.external_meter:
            self._attr_unique_id = (
                f"{entry.entry_id}_external_meter_{self.entity_description.key}"
            )
            self._attr_device_info = {
                "identifiers": {(DOMAIN, entry.entry_id, "grid_connection")},
                "name": "Growatt THOR External Meter",
                "manufacturer": "Growatt",
                "model": "THOR External Meter",
            }
        else:
            self._attr_unique_id = f"{entry.entry_id}_{self.entity_description.key}"
            self._attr_device_info = {
                "identifiers": {(DOMAIN, entry.entry_id)},
                "name": "Growatt THOR EV Charger",
                "manufacturer": "Growatt",
                "model": "THOR",
            }

    @property
    def _configuration_value(self):
        return self.coordinator.configuration_values.get(self._configuration_key)

    @property
    def native_value(self):
        return configuration_entity_state(
            self._configuration_key,
            self._configuration_value,
        )

    @property
    def available(self):
        return super().available and self.native_value is not None

    @property
    def extra_state_attributes(self):
        value = self._configuration_value
        if value is None:
            return None
        attributes = {
            "ocpp_key": value.key,
            "raw_value": value.raw_value,
            "readonly": value.readonly,
        }
        if self._has_information:
            attributes["information"] = "details"
        return attributes


# ─────────────────────────────
# Retained OCPP BootNotification metadata
# ─────────────────────────────

class OcppBootSensor(BaseSensor):
    """Expose one retained BootNotification field."""

    def __init__(self, coordinator, entry, definition):
        super().__init__(coordinator, entry, definition.entity_description.key)
        self.entity_description = definition.entity_description
        self._payload_key = definition.payload_key

    @property
    def native_value(self):
        return boot_notification_field(
            self.coordinator.boot_notification,
            self._payload_key,
        )

    @property
    def available(self):
        return super().available and self.native_value is not None


# ─────────────────────────────
# Server URL (DIAGNOSTIC - EV Charger)
# ─────────────────────────────

class ServerUrlSensor(BaseSensor):
    _attr_translation_key = "server_url"
    _attr_icon = "mdi:server"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "server_url")

    @property
    def native_value(self):
        return self.coordinator.server_url


# ─────────────────────────────
# Status (HOOFDSENSOR - EV Charger)
# ─────────────────────────────

class StatusSensor(BaseSensor):
    _attr_translation_key = "status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = OCPP_STATUS_OPTIONS
    _attr_icon = "mdi:ev-station"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "status")

    @property
    def native_value(self):
        return normalize_ocpp_status(self.coordinator.status)

    @property
    def available(self):
        return (
            super().available
            and self.coordinator.connected
            and self.coordinator.status is not None
        )

    @property
    def extra_state_attributes(self):
        return {
            "connected": self.coordinator.connected,
            "connection_started_at": self.coordinator.connection_started_at,
            "last_message_at": self.coordinator.last_message_at,
            "last_message_action": self.coordinator.last_message_action,
            "last_heartbeat_at": self.coordinator.last_heartbeat_at,
        }


# ─────────────────────────────
# Charge Point ID (HOOFDSENSOR - EV Charger)
# ─────────────────────────────

class ChargePointIdSensor(BaseSensor):
    _attr_translation_key = "charge_point_id"
    _attr_icon = "mdi:identifier"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "charge_point_id")

    @property
    def native_value(self):
        return self.coordinator.charge_point_id

    @property
    def available(self):
        return self.coordinator.charge_point_id is not None


# ─────────────────────────────
# Charging power (HOOFDSENSOR - EV Charger)
# ─────────────────────────────

class ChargingPowerSensor(BaseSensor):
    _attr_translation_key = "charging_power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "charging_power")

    @property
    def native_unit_of_measurement(self):
        return UnitOfPower.WATT

    @property
    def native_value(self):
        return self.coordinator.power if self.coordinator.power is not None else 0


# ─────────────────────────────
# Energy charged live (HOOFDSENSOR - EV Charger)
# ─────────────────────────────

class EnergyChargedSensor(BaseSensor):
    _attr_translation_key = "energy_charged"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "energy_charged")

    @property
    def native_unit_of_measurement(self):
        return UnitOfEnergy.KILO_WATT_HOUR

    @property
    def native_value(self):
        if self.coordinator.energy is None:
            return 0
        return round(self.coordinator.energy / 1000, 3)


# ─────────────────────────────
# Total energy charged - cumulatief persistent (Energy Dashboard)
# ─────────────────────────────

class TotalEnergyChargedSensor(BaseSensor):
    _attr_translation_key = "total_energy_charged"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "total_energy_charged")

    @property
    def native_unit_of_measurement(self):
        return UnitOfEnergy.KILO_WATT_HOUR

    @property
    def native_value(self):
        return round(self.coordinator.total_energy_charged, 3)


# ─────────────────────────────
# Electricity price (EV Charger)
# ─────────────────────────────

class ElectricityPriceSensor(BaseSensor):
    _attr_translation_key = "electricity_price"
    _attr_icon = "mdi:cash"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "electricity_price")
        self._attr_native_unit_of_measurement = electricity_price_unit(
            coordinator.hass
        )

    @property
    def native_value(self):
        value = self.coordinator.electricity_price
        return round(value, 2) if value is not None else None


# ─────────────────────────────
# Last session: energy (kWh)
# ─────────────────────────────

class LastSessionEnergySensor(BaseSensor):
    _attr_translation_key = "last_session_energy"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:lightning-bolt"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_session_energy")

    @property
    def native_unit_of_measurement(self):
        return UnitOfEnergy.KILO_WATT_HOUR

    @property
    def native_value(self):
        return round(self.coordinator.last_session_energy, 3) if self.coordinator.last_session_energy is not None else None


# ─────────────────────────────
# Last session: cost
# ─────────────────────────────

class LastSessionCostSensor(BaseSensor):
    _attr_translation_key = "last_session_cost"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:cash"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_session_cost")
        self._attr_native_unit_of_measurement = configured_currency(
            coordinator.hass
        )

    @property
    def native_value(self):
        return round(self.coordinator.last_session_cost, 2) if self.coordinator.last_session_cost is not None else None


# ─────────────────────────────
# Last session: duration (minutes)
# ─────────────────────────────

class LastSessionDurationSensor(BaseSensor):
    _attr_translation_key = "last_session_duration"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_session_duration")

    @property
    def native_value(self):
        minutes = self.coordinator.last_session_duration_minutes
        return round(minutes / 60, 2) if minutes is not None else None


class LastSessionEffectiveChargingDurationSensor(BaseSensor):
    """Duration with measured energy transfer during the last session."""

    _attr_translation_key = "last_session_effective_charging_duration"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:ev-plug-type2"

    def __init__(self, coordinator, entry):
        super().__init__(
            coordinator,
            entry,
            "last_session_effective_charging_duration",
        )

    @property
    def native_value(self):
        minutes = self.coordinator.last_session_effective_charging_minutes
        return round(minutes / 60, 2) if minutes is not None else None

    @property
    def extra_state_attributes(self):
        return {
            "information": "details",
            "calculation_method": "ocpp_meter_values",
            "active_power_threshold_w": 100,
        }


# ─────────────────────────────
# Last session: start time
# ─────────────────────────────

class LastSessionStartSensor(BaseSensor):
    _attr_translation_key = "last_session_start"
    _attr_icon = "mdi:clock-start"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_session_start")

    @property
    def native_value(self):
        return self.coordinator.last_session_start


# ─────────────────────────────
# Last session: end time
# ─────────────────────────────

class LastSessionEndSensor(BaseSensor):
    _attr_translation_key = "last_session_end"
    _attr_icon = "mdi:clock-end"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_session_end")

    @property
    def native_value(self):
        return self.coordinator.last_session_end


# ─────────────────────────────
# Last session: plug time
# ─────────────────────────────

class LastSessionPlugTimeSensor(BaseSensor):
    _attr_translation_key = "last_session_plug_time"
    _attr_icon = "mdi:power-plug"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_session_plug_time")

    @property
    def native_value(self):
        return self.coordinator.last_session_plug_time


# ─────────────────────────────
# Last session: unplug time
# ─────────────────────────────

class LastSessionUnplugTimeSensor(BaseSensor):
    _attr_translation_key = "last_session_unplug_time"
    _attr_icon = "mdi:power-plug-off"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_session_unplug_time")

    @property
    def native_value(self):
        return self.coordinator.last_session_unplug_time


# ─────────────────────────────
# Last session: transaction ID (DIAGNOSTIC)
# ─────────────────────────────

class LastSessionTransactionIdSensor(BaseSensor):
    _attr_translation_key = "last_session_transaction_id"
    _attr_icon = "mdi:identifier"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_session_transaction_id")

    @property
    def native_value(self):
        return self.coordinator.last_session_transaction_id


# ─────────────────────────────
# Last session: charge mode (DIAGNOSTIC)
# ─────────────────────────────

class LastSessionChargeModeSensor(BaseSensor):
    _attr_translation_key = "last_session_charge_mode"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(SESSION_CHARGE_MODE_OPTIONS)
    _attr_icon = "mdi:shield-key-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_session_charge_mode")

    @property
    def native_value(self):
        return normalize_session_charge_mode(
            self.coordinator.last_session_charge_mode
        )

    @property
    def available(self):
        return super().available and self.native_value is not None

    @property
    def extra_state_attributes(self):
        return {"raw_value": self.coordinator.last_session_charge_mode}


# ─────────────────────────────
# Last session: work mode (DIAGNOSTIC)
# ─────────────────────────────

class LastSessionWorkModeSensor(BaseSensor):
    _attr_translation_key = "last_session_work_mode"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(SESSION_WORK_MODE_OPTIONS)
    _attr_icon = "mdi:ev-station"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_session_work_mode")

    @property
    def native_value(self):
        return normalize_session_work_mode(
            self.coordinator.last_session_work_mode
        )

    @property
    def available(self):
        return super().available and self.native_value is not None

    @property
    def extra_state_attributes(self):
        return {"raw_value": self.coordinator.last_session_work_mode}


# ─────────────────────────────
# Phase currents (DIAGNOSTIC - EV Charger)
# ─────────────────────────────

class CurrentSensor(BaseSensor):
    _attr_translation_key = "current"
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, phase):
        self.phase = phase
        self._attr_translation_placeholders = {"phase": phase}
        super().__init__(coordinator, entry, f"current_{phase.lower()}")

    @property
    def native_unit_of_measurement(self):
        return UnitOfElectricCurrent.AMPERE

    @property
    def native_value(self):
        value = self.coordinator.currents.get(self.phase)
        return value if value is not None else 0


# ─────────────────────────────
# Phase voltages (DIAGNOSTIC - EV Charger)
# ─────────────────────────────

class VoltageSensor(BaseSensor):
    _attr_translation_key = "voltage"
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, phase):
        self.phase = phase
        self._attr_translation_placeholders = {"phase": phase}
        super().__init__(coordinator, entry, f"voltage_{phase.lower()}")

    @property
    def native_unit_of_measurement(self):
        return UnitOfElectricPotential.VOLT

    @property
    def native_value(self):
        value = self.coordinator.voltages.get(self.phase)
        return value if value is not None else 0


# ─────────────────────────────
# Phase power (DIAGNOSTIC - EV Charger)
# ─────────────────────────────

class PhasePowerSensor(BaseSensor):
    _attr_translation_key = "phase_power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, phase):
        self.phase = phase
        self._attr_translation_placeholders = {"phase": phase}
        super().__init__(coordinator, entry, f"power_{phase.lower()}")

    @property
    def native_unit_of_measurement(self):
        return UnitOfPower.WATT

    @property
    def native_value(self):
        value = self.coordinator.phase_power.get(self.phase)
        return value if value is not None else 0


# ─────────────────────────────
# Temperature (DIAGNOSTIC - EV Charger)
# ─────────────────────────────

class TemperatureSensor(BaseSensor):
    _attr_translation_key = "temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "temperature")

    @property
    def native_unit_of_measurement(self):
        return UnitOfTemperature.CELSIUS

    @property
    def native_value(self):
        return self.coordinator.temperature

    @property
    def available(self):
        return super().available and self.coordinator.temperature is not None


# ─────────────────────────────
# Grid / external meter
# ─────────────────────────────

class ExternalMeterHealthSensor(BaseExternalMeterSensor):
    """Show whether external Modbus measurements are trustworthy."""

    _attr_translation_key = "external_meter_health"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(EXTERNAL_METER_HEALTH_OPTIONS)
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:meter-electric-outline"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "health")

    @property
    def native_value(self):
        return self.coordinator.external_meter_health

    @property
    def available(self):
        return super().available and self.coordinator.connected

    @property
    def extra_state_attributes(self):
        return {
            **super().extra_state_attributes,
            "information": "details",
            "connector_id": self.coordinator.external_meter_fault_connector_id,
            "error_code": self.coordinator.external_meter_fault_error_code,
            "info": self.coordinator.external_meter_fault_info,
            "consecutive_timeouts": self.coordinator.meterval_consecutive_timeouts,
        }

class GridPowerSensor(BaseExternalMeterSensor):
    _attr_translation_key = "grid_power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:transmission-tower"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "power")

    @property
    def native_unit_of_measurement(self):
        return UnitOfPower.WATT

    @property
    def native_value(self):
        return self.coordinator.grid_power

    @property
    def available(self):
        return (
            super().available
            and self.coordinator.connected
            and self.coordinator.grid_power is not None
        )


class GridVoltageSensor(BaseExternalMeterSensor):
    _attr_translation_key = "grid_voltage"
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:current-ac"

    def __init__(self, coordinator, entry, phase):
        self.phase = phase
        self._attr_translation_placeholders = {"phase": phase}
        super().__init__(coordinator, entry, f"voltage_{phase.lower()}")

    @property
    def native_unit_of_measurement(self):
        return UnitOfElectricPotential.VOLT

    @property
    def native_value(self):
        return self.coordinator.grid_voltages.get(self.phase)

    @property
    def available(self):
        return (
            super().available
            and self.coordinator.connected
            and self.native_value is not None
        )


class GridCurrentSensor(BaseExternalMeterSensor):
    _attr_translation_key = "grid_current"
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:current-dc"

    def __init__(self, coordinator, entry, phase):
        self.phase = phase
        self._attr_translation_placeholders = {"phase": phase}
        super().__init__(coordinator, entry, f"current_{phase.lower()}")

    @property
    def native_unit_of_measurement(self):
        return UnitOfElectricCurrent.AMPERE

    @property
    def native_value(self):
        return self.coordinator.grid_currents.get(self.phase)

    @property
    def available(self):
        return (
            super().available
            and self.coordinator.connected
            and self.native_value is not None
        )
