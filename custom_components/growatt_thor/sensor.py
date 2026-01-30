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
            ServerUrlSensor(coordinator, entry),
            LastSessionsHistorySensor(coordinator, entry),

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

            # ── Load Balancing Grid sensors ───────
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
        """Hint: Data alleen bij Load balancing enabled."""
        if not self.coordinator.external_limit_power_enable:
            return {"note": "Only sensor data when Load balancing is enabled"}
        return None


# ─────────────────────────────
# Server URL (DIAGNOSTIC - EV Charger)
# ─────────────────────────────

class ServerUrlSensor(BaseSensor):
    _attr_name = "Server URL"
    _attr_icon = "mdi:server"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "server_url")

    @property
    def native_value(self):
        return self.coordinator.server_url


# ─────────────────────────────
# Last Sessions History (HOOFDSENSOR - EV Charger)
# ─────────────────────────────

class LastSessionsHistorySensor(BaseSensor):
    _attr_name = "Last sessions"
    _attr_icon = "mdi:history"
    _attr_state_class = None  # Text sensor

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_sessions")

    @property
    def native_value(self):
        """Return aantal sessies in history."""
        count = len(self.coordinator.session_history)
        return f"{count} session{'s' if count != 1 else ''}"

    @property
    def extra_state_attributes(self):
        """Return laatste 5 sessies als attributes."""
        if not self.coordinator.session_history:
            return {"note": "No sessions recorded yet"}

        attrs = {}
        for i, session in enumerate(self.coordinator.session_history, 1):
            # Bereken duration
            try:
                from datetime import datetime
                start = datetime.strptime(session["start_time"], "%Y-%m-%d %H:%M:%S")
                end = datetime.strptime(session["end_time"], "%Y-%m-%d %H:%M:%S")
                duration = str(end - start)
            except:
                duration = "Unknown"

            attrs[f"session_{i}"] = {
                "timestamp": session["timestamp"],
                "energy": f"{session['energy_kwh']:.3f} kWh",
                "cost": f"€{session['cost']:.2f}",
                "plug_time": session["plug_time"],
                "unplug_time": session["unplug_time"],
                "duration": duration,
                "mode": f"{session['charge_mode']}/{session['work_mode']}",
                "transaction_id": session["transaction_id"],
            }

        return attrs


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

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "charge_point_id")

    @property
    def native_value(self):
        return self.coordinator.charge_point_id

    @property
    def available(self):
        """Sensor only available when charger connected."""
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
# Energy charged (HOOFDSENSOR - EV Charger)
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
