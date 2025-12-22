from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import UnitOfPower, UnitOfEnergy, UnitOfTime
from .const import DOMAIN

# ─────────────────────────────
# Setup
# ─────────────────────────────
async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN]["coordinator"]

    sensors = []

    # Standaard sensoren
    sensors.append(GrowattThorStatusSensor(coordinator, entry))
    sensors.append(GrowattThorPowerSensor(coordinator, entry))
    sensors.append(GrowattThorEnergySensor(coordinator, entry))

    # Dynamische sensoren gebaseerd op coordinator.extra_data
    for key, meta in coordinator.extra_data.items():
        sensors.append(DynamicGrowattSensor(coordinator, entry, key, meta))

    async_add_entities(sensors)

# ─────────────────────────────
# Basisklasse
# ─────────────────────────────
class GrowattThorBaseSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry

        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }

    @property
    def available(self) -> bool:
        # Entiteit blijft bestaan, ook zonder data
        return True

# ─────────────────────────────
# Standaard sensoren
# ─────────────────────────────
class GrowattThorStatusSensor(GrowattThorBaseSensor):
    _sensor_key = "status"
    _attr_name = "Status"
    _attr_icon = "mdi:ev-station"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{self._sensor_key}"

    @property
    def native_value(self):
        return self.coordinator.status


class GrowattThorPowerSensor(GrowattThorBaseSensor):
    _sensor_key = "power"
    _attr_name = "Charging Power"
    _attr_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = "power"
    _attr_icon = "mdi:flash"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{self._sensor_key}"

    @property
    def native_value(self):
        return self.coordinator.power


class GrowattThorEnergySensor(GrowattThorBaseSensor):
    _sensor_key = "energy"
    _attr_name = "Total Energy"
    _attr_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = "energy"
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{self._sensor_key}"

    @property
    def native_value(self):
        if self.coordinator.energy is None:
            return None
        return round(self.coordinator.energy / 1000, 3)


# ─────────────────────────────
# Dynamische sensoren
# ─────────────────────────────
class DynamicGrowattSensor(GrowattThorBaseSensor):
    def __init__(self, coordinator, entry, key: str, meta: dict):
        super().__init__(coordinator, entry)
        self._sensor_key = key
        self._attr_name = meta.get("name", key.replace("_", " ").title())
        self._attr_unique_id = f"{entry.entry_id}_{self._sensor_key}"
        self._unit = meta.get("unit")
        self._icon = meta.get("icon")
        self._attr_unit_of_measurement = self._unit
        self._attr_icon = self._icon

    @property
    def native_value(self):
        # Coordinator houdt extra_data dict bij met live values
        return self.coordinator.extra_data.get(self._sensor_key)

