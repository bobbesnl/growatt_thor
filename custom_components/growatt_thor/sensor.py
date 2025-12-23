from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import UnitOfPower, UnitOfEnergy

from .const import DOMAIN


# Mapping voor dynamische sensoren: unit + icon
SENSOR_META = {
    "status": {"unit": None, "icon": "mdi:ev-station"},
    "power": {"unit": UnitOfPower.WATT, "icon": "mdi:flash"},
    "energy": {"unit": UnitOfEnergy.KILO_WATT_HOUR, "icon": "mdi:counter"},
    "transaction_id": {"unit": None, "icon": "mdi:counter"},
    "current": {"unit": "A", "icon": "mdi:current-ac"},
    "voltage": {"unit": "V", "icon": "mdi:flash"},
    "id_tag": {"unit": None, "icon": "mdi:card-account-details"},
    "mode": {"unit": None, "icon": "mdi:remote"},
    "reason": {"unit": None, "icon": "mdi:alert"},
    "lcd": {"unit": None, "icon": "mdi:screen"},
    "max_current": {"unit": "A", "icon": "mdi:current-dc"},
    "max_power": {"unit": "W", "icon": "mdi:flash"},
    "meter_start": {"unit": "Wh", "icon": "mdi:counter"},
    "meter_stop": {"unit": "Wh", "icon": "mdi:counter"},
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN]["coordinator"]

    # Maak een sensor per key in SENSOR_META
    sensors = []
    for key, meta in SENSOR_META.items():
        sensors.append(GrowattThorDynamicSensor(coordinator, entry, key, meta))

    async_add_entities(sensors)


class GrowattThorBaseSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, sensor_key: str, sensor_meta: dict):
        super().__init__(coordinator)
        self._entry = entry
        self._sensor_key = sensor_key
        self._sensor_meta = sensor_meta

        # Stabiele unique_id
        self._attr_unique_id = f"{entry.entry_id}_{self._sensor_key}"

        # Koppel aan apparaat
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }

        self._attr_icon = sensor_meta.get("icon")
        self._attr_unit_of_measurement = sensor_meta.get("unit")

    @property
    def available(self) -> bool:
        # Sensor blijft bestaan, ook zonder data
        return True


class GrowattThorDynamicSensor(GrowattThorBaseSensor):
    @property
    def name(self):
        return self._sensor_key.replace("_", " ").title()

    @property
    def native_value(self):
        value = self.coordinator.extra_data.get(self._sensor_key)

        # Als de waarde een dict is, pak alleen de "value" key
        if isinstance(value, dict) and "value" in value:
            return value["value"]

        # Meter / energie in Wh → kWh
        if self._sensor_key == "energy" and value is not None:
            try:
                return round(float(value) / 1000, 3)
            except ValueError:
                return None

        # Anders gewoon de waarde
        return value

