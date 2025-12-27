#!/bin/bash
# GROWATT THOR - CONTINUE WITH OCPP_SERVER & SENSOR PATCHES

set -e

echo "========================================================================"
echo "📝 STEP 2: OCPP SERVER & SENSOR PATCHES"
echo "========================================================================"
echo ""

# Already in feature branch from previous step
echo "📝 Updating ocpp_server.py..."

cat > custom_components/growatt_thor/ocpp_server.py << 'EOF'
"""OCPP Server implementation for Growatt THOR."""
import logging
from typing import Optional, Any, Dict, List
from datetime import datetime

_LOGGER = logging.getLogger(__name__)


class OCPPServer:
    """OCPP server handler for Growatt THOR charger."""

    def __init__(self, coordinator: Any) -> None:
        """Initialize OCPP server.
        
        Args:
            coordinator: GrowattCoordinator instance for data updates
        """
        self.coordinator = coordinator
        self._logger = _LOGGER

    async def handle_authorize(self, id_tag: str) -> bool:
        """Handle Authorize request from charger.
        
        Args:
            id_tag: RFID or card identifier
            
        Returns:
            True if authorized, False otherwise
        """
        try:
            _LOGGER.info("Authorization request for tag: %s", id_tag)
            # TODO: Implement proper authorization logic
            return True
        except Exception as exc:
            _LOGGER.error("Authorization failed: %s", exc, exc_info=True)
            return False

    async def handle_start_transaction(self, 
                                      connector_id: int,
                                      id_tag: str,
                                      meter_start: int,
                                      timestamp: str) -> int:
        """Handle StartTransaction request.
        
        Args:
            connector_id: Connector identifier
            id_tag: RFID/card tag
            meter_start: Starting meter reading (Wh)
            timestamp: Transaction start time (ISO 8601)
            
        Returns:
            Transaction ID
        """
        try:
            transaction_id = int(datetime.now().timestamp() * 1000)
            _LOGGER.info(
                "Transaction started: id=%d, tag=%s, meter=%d",
                transaction_id, id_tag, meter_start
            )
            self.coordinator.start_transaction(transaction_id, id_tag)
            return transaction_id
        except Exception as exc:
            _LOGGER.error("Failed to start transaction: %s", exc, exc_info=True)
            raise

    async def handle_stop_transaction(self,
                                     transaction_id: int,
                                     meter_stop: int,
                                     timestamp: str,
                                     reason: Optional[str] = None) -> bool:
        """Handle StopTransaction request.
        
        Args:
            transaction_id: Transaction ID to stop
            meter_stop: Ending meter reading (Wh)
            timestamp: Stop time (ISO 8601)
            reason: Reason for stopping
            
        Returns:
            True if successful
        """
        try:
            energy = meter_stop / 1000.0  # Convert Wh to kWh
            _LOGGER.info(
                "Transaction stopped: id=%d, energy=%.3f kWh, reason=%s",
                transaction_id, energy, reason
            )
            self.coordinator.stop_transaction(reason)
            return True
        except Exception as exc:
            _LOGGER.error("Failed to stop transaction: %s", exc, exc_info=True)
            return False

    async def handle_meter_values(self, 
                                 transaction_id: Optional[int],
                                 meter_values: List[Dict[str, Any]]) -> bool:
        """Handle MeterValues request.
        
        Args:
            transaction_id: Transaction ID (if during charging)
            meter_values: List of meter values
            
        Returns:
            True if processed successfully
        """
        try:
            if not meter_values:
                _LOGGER.debug("Received empty meter values")
                return True
                
            _LOGGER.debug("Processing %d meter value entries", len(meter_values))
            self.coordinator.process_meter_values(meter_values)
            return True
        except Exception as exc:
            _LOGGER.error("Failed to process meter values: %s", exc, exc_info=True)
            return False

    async def handle_status_notification(self,
                                        connector_id: int,
                                        status: str,
                                        error_code: str = "NoError",
                                        timestamp: Optional[str] = None) -> bool:
        """Handle StatusNotification request.
        
        Args:
            connector_id: Connector identifier
            status: Charger status (Idle, Charging, Faulted, etc.)
            error_code: Error code if any
            timestamp: Status time
            
        Returns:
            True if processed successfully
        """
        try:
            _LOGGER.info("Status: %s (error=%s)", status, error_code)
            self.coordinator.set_status(status)
            return True
        except Exception as exc:
            _LOGGER.error("Failed to handle status notification: %s", exc, exc_info=True)
            return False

    async def handle_data_transfer(self, 
                                  vendor_id: str,
                                  message_id: Optional[str],
                                  data: Dict[str, Any]) -> bool:
        """Handle DataTransfer request (custom Growatt data).
        
        Args:
            vendor_id: Vendor identifier (Growatt)
            message_id: Message type identifier
            data: Custom data payload
            
        Returns:
            True if processed successfully
        """
        try:
            _LOGGER.debug("DataTransfer from %s: %s", vendor_id, message_id)
            
            if message_id == "GetMeterValues":
                if "MeterValues" in data:
                    await self.handle_meter_values(None, data["MeterValues"])
                    
            elif message_id == "GetConfiguration":
                if "ConfigurationKey" in data:
                    self.coordinator.process_configuration(data["ConfigurationKey"])
                    
            elif message_id == "frozenrecord":
                self.coordinator.process_frozen_record(data)
                
            return True
        except Exception as exc:
            _LOGGER.error("Failed to handle DataTransfer: %s", exc, exc_info=True)
            return False

    async def handle_get_configuration(self,
                                      configuration_key: Optional[List[str]] = None) -> Dict[str, Any]:
        """Handle GetConfiguration request.
        
        Args:
            configuration_key: Specific keys to retrieve, or None for all
            
        Returns:
            Configuration dictionary
        """
        try:
            _LOGGER.debug("GetConfiguration request: keys=%s", configuration_key)
            # TODO: Implement proper configuration retrieval
            return {"ConfigurationKey": []}
        except Exception as exc:
            _LOGGER.error("Failed to get configuration: %s", exc, exc_info=True)
            raise

    async def handle_change_configuration(self,
                                         key: str,
                                         value: str) -> bool:
        """Handle ChangeConfiguration request.
        
        Args:
            key: Configuration key to change
            value: New value
            
        Returns:
            True if change accepted
        """
        try:
            _LOGGER.info("ChangeConfiguration: %s = %s", key, value)
            # TODO: Implement proper configuration change handling
            return True
        except Exception as exc:
            _LOGGER.error("Failed to change configuration: %s", exc, exc_info=True)
            return False

    async def handle_remote_start(self, transaction_id: int, id_tag: str) -> bool:
        """Handle RemoteStartTransaction request.
        
        Args:
            transaction_id: Transaction ID
            id_tag: RFID/card tag
            
        Returns:
            True if accepted
        """
        try:
            _LOGGER.info("Remote start requested: %s", id_tag)
            self.coordinator.start_transaction(transaction_id, id_tag)
            return True
        except Exception as exc:
            _LOGGER.error("Failed to handle remote start: %s", exc, exc_info=True)
            return False

    async def handle_remote_stop(self, transaction_id: int) -> bool:
        """Handle RemoteStopTransaction request.
        
        Args:
            transaction_id: Transaction ID to stop
            
        Returns:
            True if accepted
        """
        try:
            _LOGGER.info("Remote stop requested: %d", transaction_id)
            self.coordinator.stop_transaction("Remote")
            return True
        except Exception as exc:
            _LOGGER.error("Failed to handle remote stop: %s", exc, exc_info=True)
            return False
EOF

echo "✅ ocpp_server.py patched"
echo ""

# Step: Update sensor.py
echo "📝 Updating sensor.py..."

cat > custom_components/growatt_thor/sensor.py << 'EOF'
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
EOF

echo "✅ sensor.py patched"
echo ""

# Step: Commit all changes
echo "📤 Committing all patches..."
git add custom_components/growatt_thor/ocpp_server.py custom_components/growatt_thor/sensor.py
git commit -m "feat: add comprehensive docstrings and type hints to OCPP and sensor modules

- ocpp_server.py: Complete docstrings for all handler methods, type hints, logging improvements
- sensor.py: Type hints, docstring improvements, entity categories configured
- Consistent error handling across all methods"

echo "✅ All patches committed"
echo ""

# Step: Push to GitHub
echo "📡 Pushing to GitHub..."
git push origin feature/code-quality-improvements
echo "✅ Pushed all changes"
echo ""

echo "========================================================================"
echo "✅ ALL PATCHES APPLIED!"
echo "========================================================================"
echo ""
echo "Ready to create Pull Request!"
echo "Go to: https://github.com/bobbesnl/growatt_thor/pull/new/feature/code-quality-improvements"
echo ""
echo "========================================================================"
