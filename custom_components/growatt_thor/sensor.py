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
)

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities(
        [
            # ── Status / totaal (hoofdsensors) ─────────
            StatusSensor(coordinator, entry),
            ChargePointIdSensor(coordinator, entry),
            ChargingPowerSensor(coordinator, entry),
            EnergyChargedSensor(coordinator, entry),

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

            # ── Grid connection (apart device!) ───────
            GridPowerSensor(coordinator, entry),
            GridVoltageSensor(coordinator, entry, "L1"),
            GridVoltageSensor(coordinator, entry, "L2"),
            GridVoltageSensor(coordinator, entry, "L3"),
            GridCurrentSensor(coordinator, entry, "L1"),
            GridCurrentSensor(coordinator, entry, "L2"),
            GridCurrentSensor(coordinator, entry, "L3"),
        ]
    )


# ─────────────────────────────
# Base voor charger sensors
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
# Base voor grid sensors (apart device!)
# ─────────────────────────────

class BaseGridSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, key):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_grid_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_grid")},
            "name": "Growatt THOR Grid Connection",
            "manufacturer": "Growatt",
            "model": "External Meter",
            "via_device": (DOMAIN, entry.entry_id),
        }


# ─────────────────────────────
# Status (HOOFDSENSOR)
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
# Charge Point ID (HOOFDSENSOR)
# ─────────────────────────────

class ChargePointIdSensor(BaseSensor):
    _attr_name = "Charge Point ID"
    _attr_icon = "mdi:identifier"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "charge_point_id")

    @property
    def native_value(self):
        return self.coordinator.charge_point_id

    @property
    def available(self):
        """Sensor is alleen beschikbaar als charger verbonden is."""
        return self.coordinator.charge_point_id is not None


# ─────────────────────────────
# Charging power (HOOFDSENSOR)
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
# Energy charged (HOOFDSENSOR)
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
# Phase currents (DIAGNOSTIC)
# ─────────────────────────────

class CurrentSensor(BaseSensor):
    _attr_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, phase):
        self.phase = phase
        self._attr_name = f"Current {phase}"
        super().__init__(coordinator, entry, f"current_{phase.lower()}")

    @property
    def native_value(self):
        return self.coordinator.currents.get(self.phase)


# ─────────────────────────────
# Phase voltages (DIAGNOSTIC)
# ─────────────────────────────

class VoltageSensor(BaseSensor):
    _attr_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, phase):
        self.phase = phase
        self._attr_name = f"Voltage {phase}"
        super().__init__(coordinator, entry, f"voltage_{phase.lower()}")

    @property
    def native_value(self):
        return self.coordinator.voltages.get(self.phase)


# ─────────────────────────────
# Phase power (DIAGNOSTIC)
# ─────────────────────────────

class PhasePowerSensor(BaseSensor):
    _attr_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, phase):
        self.phase = phase
        self._attr_name = f"Power {phase}"
        super().__init__(coordinator, entry, f"power_{phase.lower()}")

    @property
    def native_value(self):
        return self.coordinator.phase_power.get(self.phase)


# ─────────────────────────────
# Temperature (DIAGNOSTIC)
# ─────────────────────────────

class TemperatureSensor(BaseSensor):
    _attr_name = "Temperature"
    _attr_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "temperature")

    @property
    def native_value(self):
        return self.coordinator.temperature


# ─────────────────────────────
# Grid / External Meter (APART DEVICE!)
# ─────────────────────────────

class GridPowerSensor(BaseGridSensor):
    _attr_name = "Power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:transmission-tower"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "power")
        # ✅ FIX: Unit of measurement MOET in __init__ gezet worden
        self._attr_unit_of_measurement = UnitOfPower.WATT

    @property
    def native_value(self):
        return self.coordinator.grid_power


class GridVoltageSensor(BaseGridSensor):
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:transmission-tower"

    def __init__(self, coordinator, entry, phase):
        self.phase = phase
        self._attr_name = f"Voltage {phase}"
        super().__init__(coordinator, entry, f"voltage_{phase.lower()}")
        # ✅ FIX: Unit of measurement MOET in __init__ gezet worden
        self._attr_unit_of_measurement = UnitOfElectricPotential.VOLT

    @property
    def native_value(self):
        return self.coordinator.grid_voltages.get(self.phase)


class GridCurrentSensor(BaseGridSensor):
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:transmission-tower"

    def __init__(self, coordinator, entry, phase):
        self.phase = phase
        self._attr_name = f"Current {phase}"
        super().__init__(coordinator, entry, f"current_{phase.lower()}")
        # ✅ FIX: Unit of measurement MOET in __init__ gezet worden
        self._attr_unit_of_measurement = UnitOfElectricCurrent.AMPERE

    @property
    def native_value(self):
        return self.coordinator.grid_currents.get(self.phase)

