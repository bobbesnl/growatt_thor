from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import UnitOfPower, UnitOfEnergy

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities(
        [
            StatusSensor(coordinator, entry),
            PowerSensor(coordinator, entry),
            EnergySensor(coordinator, entry),
            TransactionSensor(coordinator, entry),
            IdTagSensor(coordinator, entry),
            LastSessionEnergySensor(coordinator, entry),
            LastSessionCostSensor(coordinator, entry),
        ]
    )


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


class StatusSensor(BaseSensor):
    _attr_name = "Status"
    _attr_icon = "mdi:ev-station"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "status")

    @property
    def native_value(self):
        return self.coordinator.status


class PowerSensor(BaseSensor):
    _attr_name = "Charging Power"
    _attr_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "power")

    @property
    def native_value(self):
        return self.coordinator.power


class EnergySensor(BaseSensor):
    _attr_name = "Total Energy"
    _attr_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "energy")

    @property
    def native_value(self):
        if self.coordinator.energy is None:
            return None
        return round(self.coordinator.energy / 1000, 3)


class TransactionSensor(BaseSensor):
    _attr_name = "Transaction ID"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "transaction")

    @property
    def native_value(self):
        return self.coordinator.transaction_id


class IdTagSensor(BaseSensor):
    _attr_name = "ID Tag"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "id_tag")

    @property
    def native_value(self):
        return self.coordinator.id_tag


class LastSessionEnergySensor(BaseSensor):
    _attr_name = "Last Session Energy"
    _attr_unit_of_measurement = UnitOfEnergy.WATT_HOUR

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_energy")

    @property
    def native_value(self):
        return self.coordinator.last_session_energy


class LastSessionCostSensor(BaseSensor):
    _attr_name = "Last Session Cost"
    _attr_icon = "mdi:currency-eur"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_cost")

    @property
    def native_value(self):
        return self.coordinator.last_session_cost

