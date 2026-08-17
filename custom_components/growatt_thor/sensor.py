from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
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

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities(
        [
            # ── Status / live ─────────────────────────
            StatusSensor(coordinator, entry),
            ChargePointIdSensor(coordinator, entry),
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
            GridPowerSensor(coordinator, entry),
            GridVoltageSensor(coordinator, entry, "L1"),
            GridVoltageSensor(coordinator, entry, "L2"),
            GridVoltageSensor(coordinator, entry, "L3"),
            GridCurrentSensor(coordinator, entry, "L1"),
            GridCurrentSensor(coordinator, entry, "L2"),
            GridCurrentSensor(coordinator, entry, "L3"),

            # ── Elektricteitstarief ───────────────────
            ElectricityPriceSensor(coordinator, entry),
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


# ─────────────────────────────
# Base voor Load balancing sensors (Load balancing device!)
# ─────────────────────────────

class BaseLoadBalancingSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, key):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_load_balancing_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id, "grid_connection")},
            "name": "Growatt THOR Load balancing",
            "manufacturer": "Growatt",
            "model": "THOR Load balancing",
        }

    @property
    def extra_state_attributes(self):
        if not self.coordinator.external_limit_power_enable:
            return {"note": "Only sensor data when Load balancing is enabled"}
        return None


# ─────────────────────────────
# Server URL (DIAGNOSTIC - EV Charger)
# ─────────────────────────────

class ServerUrlSensor(BaseSensor):
    _attr_name = "Server URL"
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
    _attr_name = "Status"
    _attr_icon = "mdi:ev-station"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "status")

    @property
    def native_value(self):
        return self.coordinator.status


# ─────────────────────────────
# Charge Point ID (HOOFDSENSOR - EV Charger)
# ─────────────────────────────

class ChargePointIdSensor(BaseSensor):
    _attr_name = "Charge Point ID"
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
    _attr_name = "Charging Power"
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
    _attr_name = "Energy Charged"
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
    _attr_name = "Total Energy Charged"
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
    _attr_name = "Electricity Price"
    _attr_icon = "mdi:currency-eur"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "EUR/kWh"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "electricity_price")

    @property
    def native_value(self):
        value = self.coordinator.electricity_price
        return round(value, 2) if value is not None else None


# ─────────────────────────────
# Last session: energy (kWh)
# ─────────────────────────────

class LastSessionEnergySensor(BaseSensor):
    _attr_name = "Last Session Energy"
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
    _attr_name = "Last Session Cost"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:currency-eur"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_session_cost")

    @property
    def native_value(self):
        return round(self.coordinator.last_session_cost, 2) if self.coordinator.last_session_cost is not None else None


# ─────────────────────────────
# Last session: duration (minutes)
# ─────────────────────────────

class LastSessionDurationSensor(BaseSensor):
    _attr_name = "Last Session Duration"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_session_duration")

    @property
    def native_unit_of_measurement(self):
        return UnitOfTime.MINUTES

    @property
    def native_value(self):
        return self.coordinator.last_session_duration_minutes


# ─────────────────────────────
# Last session: start time
# ─────────────────────────────

class LastSessionStartSensor(BaseSensor):
    _attr_name = "Last Session Start"
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
    _attr_name = "Last Session End"
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
    _attr_name = "Last Session Plug Time"
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
    _attr_name = "Last Session Unplug Time"
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
    _attr_name = "Last Session Transaction ID"
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
    _attr_name = "Last Session Charge Mode"
    _attr_icon = "mdi:cog-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_session_charge_mode")

    @property
    def native_value(self):
        return self.coordinator.last_session_charge_mode


# ─────────────────────────────
# Last session: work mode (DIAGNOSTIC)
# ─────────────────────────────

class LastSessionWorkModeSensor(BaseSensor):
    _attr_name = "Last Session Work Mode"
    _attr_icon = "mdi:cog-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_session_work_mode")

    @property
    def native_value(self):
        return self.coordinator.last_session_work_mode


# ─────────────────────────────
# Phase currents (DIAGNOSTIC - EV Charger)
# ─────────────────────────────

class CurrentSensor(BaseSensor):
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, phase):
        self.phase = phase
        self._attr_name = f"Current {phase}"
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
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, phase):
        self.phase = phase
        self._attr_name = f"Voltage {phase}"
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
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, phase):
        self.phase = phase
        self._attr_name = f"Power {phase}"
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
    _attr_name = "Temperature"
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
        value = self.coordinator.temperature
        return value if value is not None else 0


# ─────────────────────────────
# Grid / External Meter (LOAD BALANCING DEVICE!)
# ─────────────────────────────

class GridPowerSensor(BaseLoadBalancingSensor):
    _attr_name = "Grid power"
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
        return self.coordinator.grid_power if self.coordinator.grid_power is not None else 0


class GridVoltageSensor(BaseLoadBalancingSensor):
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:current-ac"

    def __init__(self, coordinator, entry, phase):
        self.phase = phase
        self._attr_name = f"Grid voltage {phase}"
        super().__init__(coordinator, entry, f"voltage_{phase.lower()}")

    @property
    def native_unit_of_measurement(self):
        return UnitOfElectricPotential.VOLT

    @property
    def native_value(self):
        value = self.coordinator.grid_voltages.get(self.phase)
        return value if value is not None else 0


class GridCurrentSensor(BaseLoadBalancingSensor):
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:current-dc"

    def __init__(self, coordinator, entry, phase):
        self.phase = phase
        self._attr_name = f"Grid current {phase}"
        super().__init__(coordinator, entry, f"current_{phase.lower()}")

    @property
    def native_unit_of_measurement(self):
        return UnitOfElectricCurrent.AMPERE

    @property
    def native_value(self):
        value = self.coordinator.grid_currents.get(self.phase)
        return value if value is not None else 0
