from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import (
    UnitOfPower,
    UnitOfEnergy,
    UnitOfElectricCurrent,
)

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities(
        [
            # Status / meting
            StatusSensor(coordinator, entry),
            PowerSensor(coordinator, entry),
            EnergySensor(coordinator, entry),

            # Config (Growatt)
            MaxCurrentSensor(coordinator, entry),
            ExternalLimitPowerSensor(coordinator, entry),
            ExternalLimitPowerEnableSensor(coordinator, entry),
            ChargerModeSensor(coordinator, entry),
            ServerURLSensor(coordinator, entry),
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


# ─────────────────────────────
# Status & meting
# ─────────────────────────────

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


# ─────────────────────────────
# 🔑 Config sensors (Growatt)
# ─────────────────────────────

class MaxCurrentSensor(BaseSensor):
    _attr_name = "Max Current"
    _attr_unit_of_measurement = UnitOfElectricCurrent.AMPERE

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "G_MaxCurrent")

    @property
    def native_value(self):
        return self.coordinator.config.get("G_MaxCurrent")


class ExternalLimitPowerSensor(BaseSensor):
    _attr_name = "Loadbalance Max Power"
    _attr_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "G_ExternalLimitPower")

    @property
    def native_value(self):
        return self.coordinator.config.get("G_ExternalLimitPower")


class ExternalLimitPowerEnableSensor(BaseSensor):
    _attr_name = "Loadbalance Enabled"
    _attr_icon = "mdi:transmission-tower"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "G_ExternalLimitPowerEnable")

    @property
    def native_value(self):
        return self.coordinator.config.get("G_ExternalLimitPowerEnable")


class ChargerModeSensor(BaseSensor):
    _attr_name = "Charger Mode"
    _attr_icon = "mdi:ev-plug-type2"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "G_ChargerMode")

    @property
    def native_value(self):
        return self.coordinator.config.get("G_ChargerMode")


class ServerURLSensor(BaseSensor):
    _attr_name = "OCPP Server URL"
    _attr_icon = "mdi:server-network"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "G_ServerURL")

    @property
    def native_value(self):
        return self.coordinator.config.get("G_ServerURL")

