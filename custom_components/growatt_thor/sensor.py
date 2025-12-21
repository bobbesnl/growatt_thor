from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities(
        [
            GrowattThorStatusSensor(coordinator),
            GrowattThorPowerSensor(coordinator),
            GrowattThorEnergySensor(coordinator),
        ],
        update_before_add=True,
    )


class GrowattThorBaseSensor(SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        self.coordinator = coordinator

    @property
    def available(self):
        return self.coordinator.charge_point_id is not None


class GrowattThorStatusSensor(GrowattThorBaseSensor):
    _attr_name = "Status"
    _attr_icon = "mdi:ev-station"

    @property
    def unique_id(self):
        return f"{self.coordinator.charge_point_id}_status"

    @property
    def native_value(self):
        return self.coordinator.status


class GrowattThorPowerSensor(GrowattThorBaseSensor):
    _attr_name = "Charging Power"
    _attr_unit_of_measurement = "W"
    _attr_device_class = "power"
    _attr_icon = "mdi:flash"

    @property
    def unique_id(self):
        return f"{self.coordinator.charge_point_id}_power"

    @property
    def native_value(self):
        return self.coordinator.power


class GrowattThorEnergySensor(GrowattThorBaseSensor):
    _attr_name = "Total Energy"
    _attr_unit_of_measurement = "kWh"
    _attr_device_class = "energy"
    _attr_icon = "mdi:counter"

    @property
    def unique_id(self):
        return f"{self.coordinator.charge_point_id}_energy"

    @property
    def native_value(self):
        if self.coordinator.energy is None:
            return None

        # Growatt stuurt meestal Wh → omzetten naar kWh
        return round(self.coordinator.energy / 1000, 3)

