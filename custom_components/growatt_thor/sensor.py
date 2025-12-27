"""Sensor entities for Growatt THOR EV Charger."""
from __future__ import annotations

from typing import Optional, Any

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
    """Set up sensor entities for Growatt THOR.
    
    Args:
        hass: Home Assistant instance
        entry: Config entry
        async_add_entities: Callback to add entities
    """
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities(
        [
            # ── Status / Totaal ────────────────────────────────────────────
            StatusSensor(coordinator, entry),
            ChargingPowerSensor(coordinator, entry),
            EnergyChargedSensor(coordinator, entry),

            # ── Fase-specifiek ─────────────────────────────────────────────
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


# ──────────────────────────────────────────────────────────────────────────
# Base Sensor Class
# ──────────────────────────────────────────────────────────────────────────

class BaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for Growatt THOR sensors."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, key: str) -> None:
        """Initialize sensor.
        
        Args:
            coordinator: GrowattCoordinator instance
            entry: Config entry
            key: Unique key for sensor
        """
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }


# ──────────────────────────────────────────────────────────────────────────
# Status Sensor
# ──────────────────────────────────────────────────────────────────────────

class StatusSensor(BaseSensor):
    """Charger status sensor (Idle, Charging, Faulted, etc.)."""

    _attr_name = "Status"
    _attr_icon = "mdi:ev-station"
    _attr_entity_category = None  # Main status, not diagnostic

    def __init__(self, coordinator, entry) -> None:
        """Initialize status sensor."""
        super().__init__(coordinator, entry, "status")

    @property
    def native_value(self) -> Optional[str]:
        """Return current status."""
        return self.coordinator.status


# ──────────────────────────────────────────────────────────────────────────
# Power Sensor
# ──────────────────────────────────────────────────────────────────────────

class ChargingPowerSensor(BaseSensor):
    """Total charging power sensor (sum of all phases)."""

    _attr_name = "Charging Power"
    _attr_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = None  # Main measurement

    def __init__(self, coordinator, entry) -> None:
        """Initialize charging power sensor."""
        super().__init__(coordinator, entry, "charging_power")

    @property
    def native_value(self) -> Optional[float]:
        """Return current charging power in Watts."""
        return self.coordinator.power


# ──────────────────────────────────────────────────────────────────────────
# Energy Sensor
# ──────────────────────────────────────────────────────────────────────────

class EnergyChargedSensor(BaseSensor):
    """Energy charged in current session sensor."""

    _attr_name = "Energy Charged"
    _attr_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = None  # Main measurement

    def __init__(self, coordinator, entry) -> None:
        """Initialize energy charged sensor."""
        super().__init__(coordinator, entry, "energy_charged")

    @property
    def native_value(self) -> Optional[float]:
        """Return energy charged in kWh (converted from Wh)."""
        if self.coordinator.energy is None:
            return None
        return round(self.coordinator.energy / 1000, 3)


# ──────────────────────────────────────────────────────────────────────────
# Current Sensors (Per Phase)
# ──────────────────────────────────────────────────────────────────────────

class CurrentSensor(BaseSensor):
    """Phase current sensor."""

    _attr_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry, phase: str) -> None:
        """Initialize current sensor.
        
        Args:
            coordinator: GrowattCoordinator instance
            entry: Config entry
            phase: Phase identifier (L1, L2, or L3)
        """
        self.phase = phase
        self._attr_name = f"Current {phase}"
        super().__init__(coordinator, entry, f"current_{phase.lower()}")

    @property
    def native_value(self) -> Optional[float]:
        """Return phase current in Amperes."""
        return self.coordinator.currents.get(self.phase)


# ──────────────────────────────────────────────────────────────────────────
# Voltage Sensors (Per Phase)
# ──────────────────────────────────────────────────────────────────────────

class VoltageSensor(BaseSensor):
    """Phase voltage sensor."""

    _attr_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry, phase: str) -> None:
        """Initialize voltage sensor.
        
        Args:
            coordinator: GrowattCoordinator instance
            entry: Config entry
            phase: Phase identifier (L1, L2, or L3)
        """
        self.phase = phase
        self._attr_name = f"Voltage {phase}"
        super().__init__(coordinator, entry, f"voltage_{phase.lower()}")

    @property
    def native_value(self) -> Optional[float]:
        """Return phase voltage in Volts."""
        return self.coordinator.voltages.get(self.phase)


# ──────────────────────────────────────────────────────────────────────────
# Power Sensors (Per Phase)
# ──────────────────────────────────────────────────────────────────────────

class PhasePowerSensor(BaseSensor):
    """Phase power sensor."""

    _attr_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry, phase: str) -> None:
        """Initialize phase power sensor.
        
        Args:
            coordinator: GrowattCoordinator instance
            entry: Config entry
            phase: Phase identifier (L1, L2, or L3)
        """
        self.phase = phase
        self._attr_name = f"Power {phase}"
        super().__init__(coordinator, entry, f"power_{phase.lower()}")

    @property
    def native_value(self) -> Optional[float]:
        """Return phase power in Watts."""
        return self.coordinator.phase_power.get(self.phase)


# ──────────────────────────────────────────────────────────────────────────
# Temperature Sensor
# ──────────────────────────────────────────────────────────────────────────

class TemperatureSensor(BaseSensor):
    """Charger temperature sensor."""

    _attr_name = "Temperature"
    _attr_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry) -> None:
        """Initialize temperature sensor."""
        super().__init__(coordinator, entry, "temperature")

    @property
    def native_value(self) -> Optional[float]:
        """Return charger temperature in Celsius."""
        return self.coordinator.temperature
