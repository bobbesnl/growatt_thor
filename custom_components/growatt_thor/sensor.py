from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import UnitOfPower, UnitOfEnergy, UnitOfCurrent, UnitOfElectricPotential

from .const import DOMAIN

# ─────────────────────────────
# Dynamische sensor-definities op basis van JSON logs
# ─────────────────────────────
SENSOR_DEFINITIONS = [
    # Boot & connectie
    {"key": "chargePointVendor", "name": "Vendor", "icon": "mdi:factory"},
    {"key": "chargePointModel", "name": "Model", "icon": "mdi:robot-industrial"},
    {"key": "firmwareVersion", "name": "Firmware Version", "icon": "mdi:chip"},
    {"key": "serialNumber", "name": "Serial Number", "icon": "mdi:barcode"},

    # Status & lifecycle
    {"key": "status", "name": "Status", "icon": "mdi:ev-station"},
    {"key": "errorCode", "name": "Error Code", "icon": "mdi:alert-circle"},
    {"key": "connectorId", "name": "Connector ID", "icon": "mdi:power-plug"},
    {"key": "transactionId", "name": "Transaction ID", "icon": "mdi:receipt"},

    # Laden starten / stoppen
    {"key": "idTag", "name": "Last Authorized ID", "icon": "mdi:account-key"},
    {"key": "meterStart", "name": "Meter Start", "unit": UnitOfEnergy.KILO_WATT_HOUR, "convert_wh_to_kwh": True, "icon": "mdi:counter"},
    {"key": "meterStop", "name": "Meter Stop", "unit": UnitOfEnergy.KILO_WATT_HOUR, "convert_wh_to_kwh": True, "icon": "mdi:counter"},
    {"key": "startReason", "name": "Start Reason", "icon": "mdi:play-circle-outline"},
    {"key": "stopReason", "name": "Stop Reason", "icon": "mdi:stop-circle-outline"},

    # Metingen (MeterValues)
    {"key": "Power.Active.Import", "name": "Active Power", "unit": UnitOfPower.WATT, "device_class": "power", "icon": "mdi:flash"},
    {"key": "Energy.Active.Import.Register", "name": "Energy Imported", "unit": UnitOfEnergy.KILO_WATT_HOUR, "convert_wh_to_kwh": True, "device_class": "energy", "icon": "mdi:counter"},
    {"key": "Current.Import", "name": "Current", "unit": UnitOfCurrent.AMPERE, "device_class": "current", "icon": "mdi:current-ac"},
    {"key": "Voltage", "name": "Voltage", "unit": UnitOfElectricPotential.VOLT, "device_class": "voltage", "icon": "mdi:flash"},

    # Vendor-specifiek (Growatt)
    {"key": "maxCurrent", "name": "Max Current", "unit": UnitOfCurrent.AMPERE, "icon": "mdi:current-ac"},
    {"key": "maxPower", "name": "Max Power", "unit": UnitOfPower.WATT, "icon": "mdi:flash"},
    {"key": "startTime", "name": "Start Time", "icon": "mdi:clock-start"},
    {"key": "stopTime", "name": "Stop Time", "icon": "mdi:clock-end"},
    {"key": "lcd", "name": "LCD Status", "icon": "mdi:monitor"},
    {"key": "mode", "name": "Charge Mode", "icon": "mdi:ev-station"},
]

# ─────────────────────────────
# Setup entry
# ─────────────────────────────
async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN]["coordinator"]

    sensors = [
        GrowattThorDynamicSensor(coordinator, entry, definition)
        for definition in SENSOR_DEFINITIONS
    ]

    async_add_entities(sensors)


# ─────────────────────────────
# Basisklasse voor dynamische sensoren
# ─────────────────────────────
class GrowattThorBaseSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_available = True  # altijd zichtbaar

        # Koppelen aan apparaat
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }


# ─────────────────────────────
# Dynamische sensorklasse
# ─────────────────────────────
class GrowattThorDynamicSensor(GrowattThorBaseSensor):
    def __init__(self, coordinator, entry, definition):
        super().__init__(coordinator, entry)
        self.definition = definition

        self._sensor_key = definition["key"]

        # stabiele unique_id gebaseerd op config entry + key
        self._attr_unique_id = f"{entry.entry_id}_{self._sensor_key}"

        # attributen
        self._attr_name = definition.get("name")
        self._attr_icon = definition.get("icon")
        self._attr_unit_of_measurement = definition.get("unit")
        self._attr_device_class = definition.get("device_class")

    @property
    def native_value(self):
        # eerst gewone attribuut uit coordinator
        value = getattr(self.coordinator, self._sensor_key, None)
        if value is None:
            # fallback: kijk in vendor_data dict (DataTransfer)
            vendor_data = getattr(self.coordinator, "vendor_data", {})
            value = vendor_data.get(self._sensor_key, None)

        if value is None:
            return None

        # optionele conversie van Wh → kWh
        if self.definition.get("convert_wh_to_kwh"):
            return round(float(value) / 1000, 3)
        try:
            return float(value)
        except (ValueError, TypeError):
            return value

