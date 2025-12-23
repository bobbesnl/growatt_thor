from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import UnitOfPower, UnitOfEnergy, UnitOfElectricCurrent, UnitOfElectricPotential

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities(
        [
            GrowattThorStatusSensor(coordinator, entry),
            GrowattThorPowerSensor(coordinator, entry),
            GrowattThorEnergySensor(coordinator, entry),
            GrowattThorVoltageSensor(coordinator, entry),
            GrowattThorCurrentSensor(coordinator, entry),
            GrowattThorTransactionSensor(coordinator, entry),
            GrowattThorIdTagSensor(coordinator, entry),
            GrowattThorMaxCurrentSensor(coordinator, entry),
            GrowattThorMaxPowerSensor(coordinator, entry),
            GrowattThorModeSensor(coordinator, entry),
            GrowattThorLCDSensor(coordinator, entry),
        ]
    )


class GrowattThorBaseSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{self._sensor_key}"

        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }

    @property
    def available(self) -> bool:
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
        return round(self.coordinator.energy / 1000, 3)


class GrowattThorVoltageSensor(GrowattThorBaseSensor):
    _sensor_key = "voltage"
    _attr_name = "Voltage"
    _attr_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_icon = "mdi:flash-outline"

    @property
    def native_value(self):
        return self.coordinator.voltage


class GrowattThorCurrentSensor(GrowattThorBaseSensor):
    _sensor_key = "current"
    _attr_name = "Current"
    _attr_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_icon = "mdi:current-ac"

    @property
    def native_value(self):
        return self.coordinator.current


class GrowattThorTransactionSensor(GrowattThorBaseSensor):
    _sensor_key = "transaction_id"
    _attr_name = "Transaction ID"
    _attr_icon = "mdi:counter"

    @property
    def native_value(self):
        return self.coordinator.transaction_id


class GrowattThorIdTagSensor(GrowattThorBaseSensor):
    _sensor_key = "id_tag"
    _attr_name = "ID Tag"
    _attr_icon = "mdi:card-account-details"

    @property
    def native_value(self):
        return self.coordinator.id_tag


class GrowattThorMaxCurrentSensor(GrowattThorBaseSensor):
    _sensor_key = "max_current"
    _attr_name = "Max Current"
    _attr_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_icon = "mdi:current-dc"

    @property
    def native_value(self):
        return self.coordinator.max_current


class GrowattThorMaxPowerSensor(GrowattThorBaseSensor):
    _sensor_key = "max_power"
    _attr_name = "Max Power"
    _attr_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:flash"

    @property
    def native_value(self):
        return self.coordinator.max_power


class GrowattThorModeSensor(GrowattThorBaseSensor):
    _sensor_key = "mode"
    _attr_name = "Charging Mode"
    _attr_icon = "mdi:remote"

    @property
    def native_value(self):
        return self.coordinator.mode


class GrowattThorLCDSensor(GrowattThorBaseSensor):
    _sensor_key = "lcd"
    _attr_name = "LCD Message"
    _attr_icon = "mdi:screen"

    @property
    def native_value(self):
        return self.coordinator.lcd

