from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import UnitOfPower, UnitOfEnergy

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities(
        [
            GrowattThorStatusSensor(coordinator, entry),
            GrowattThorPowerSensor(coordinator, entry),
            GrowattThorEnergySensor(coordinator, entry),
        ]
    )


class GrowattThorBaseSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry

        # 👉 STABIELE unique_id, onafhankelijk van charge_point_id
        self._attr_unique_id = f"{entry.entry_id}_{self._sensor_key}"

        # 👉 Koppelen aan apparaat
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


class GrowattThorStatusSensor(GrowattThorBaseSensor):
    _sensor_key = "status"
    _attr_name = "Status"
    _attr_icon = "mdi:ev-station"

    @property
    def native_value(self):
        return self.coordinator.status


class GrowattThorPowerSensor(GrowattThorBaseSensor):
    _sensor_key = "power"
    _attr_name = "Charging Power"
    _attr_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = "power"
    _attr_icon = "mdi:flash"

    @property
    def native_value(self):
        return self.coordinator.power


class GrowattThorEnergySensor(GrowattThorBaseSensor):
    _sensor_key = "energy"
    _attr_name = "Total Energy"
    _attr_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = "energy"
    _attr_icon = "mdi:counter"

    @property
    def native_value(self):
        if self.coordinator.energy is None:
            return None

        # Growatt stuurt meestal Wh → omzetten naar kWh
        return round(self.coordinator.energy / 1000, 3)

