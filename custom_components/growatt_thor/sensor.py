from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import (
    UnitOfPower,
    UnitOfEnergy,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfTemperature,
)

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities(
        [
            # ── Status / totaal ─────────────────────────
            StatusSensor(coordinator, entry),
            ChargingPowerSensor(coordinator, entry),
            EnergyChargedSensor(coordinator, entry),

            # ── Fase-specifiek ─────────────────────────
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
        ]
    )


# ─────────────────────────────
# Base
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
# Status
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
# Charging power (FIXED)
# ─────────────────────────────

class ChargingPowerSensor(BaseSensor):
    _attr_name = "Charging Power"
    _attr_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "charging_power")

    @property
    def native_value(self):
        return self.coordinator.power


# ─────────────────────────────
# Energy charged (FIXED)
# ─────────────────────────────

class EnergyChargedSensor(BaseSensor):
    _attr_name = "Energy Charged"
    _attr_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "energy_charged")

    @property
    def native_value(self):
        if self.coordinator.energy is None:
            return None
        return round(self.coordinator.energy / 1000, 3)


# ─────────────────────────────
# Phase currents
# ─────────────────────────────

class CurrentSensor(BaseSensor):
    _attr_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry, phase):
        self.phase = phase
        self._attr_name = f"Current {phase}"
        super().__init__(coordinator, entry, f"current_{phase.lower()}")

    @property
    def native_value(self):
        return self.coordinator.currents.get(self.phase)


# ─────────────────────────────
# Phase voltages
# ─────────────────────────────

class VoltageSensor(BaseSensor):
    _attr_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry, phase):
        self.phase = phase
        self._attr_name = f"Voltage {phase}"
        super().__init__(coordinator, entry, f"voltage_{phase.lower()}")

    @property
    def native_value(self):
        return self.coordinator.voltages.get(self.phase)


# ─────────────────────────────
# Phase power
# ─────────────────────────────

class PhasePowerSensor(BaseSensor):
    _attr_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry, phase):
        self.phase = phase
        self._attr_name = f"Power {phase}"
        super().__init__(coordinator, entry, f"power_{phase.lower()}")

    @property
    def native_value(self):
        return self.coordinator.phase_power.get(self.phase)


# ─────────────────────────────
# Temperature
# ─────────────────────────────

class TemperatureSensor(BaseSensor):
    _attr_name = "Temperature"
    _attr_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "temperature")

    @property
    def native_value(self):
        return self.coordinator.temperature

