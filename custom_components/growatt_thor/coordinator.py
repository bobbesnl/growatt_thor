"""Coordinator for Growatt THOR OCPP data management."""
import logging
from datetime import datetime, timezone

_LOGGER = logging.getLogger(__name__)


class GrowattCoordinator:
    """Coordinator to manage Growatt THOR charger data."""

    def __init__(self, hass):
        """Initialize coordinator.
        
        Args:
            hass: Home Assistant instance
        """
        self.hass = hass
        self.charge_point_id = None
        self.status = None
        self.power = None
        self.energy = None
        
        # Config cache for future use (GetConfiguration responses)
        self.config = {}

    def now(self):
        """Return current UTC timestamp in ISO format with Z suffix.
        
        Returns:
            str: ISO 8601 timestamp (e.g., '2025-12-27T14:06:32Z')
        """
        return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')

    def set_charge_point(self, cp_id):
        """Set charge point ID.
        
        Args:
            cp_id: Charge point identifier string
        """
        if self.charge_point_id != cp_id:
            self.charge_point_id = cp_id
            _LOGGER.info("Charge point connected: %s", cp_id)

    def set_status(self, status):
        """Set charger status.
        
        Args:
            status: Status value (enum or string)
        """
        # Handle both enum and string values
        value = status.value if hasattr(status, "value") else status
        
        if self.status != value:
            self.status = value
            _LOGGER.info("Status changed to: %s", value)

    def process_meter_values(self, meter_values):
        """Process meter values from OCPP MeterValues message.
        
        Args:
            meter_values: List of meter value entries from OCPP
        """
        if not meter_values:
            _LOGGER.debug("Received empty meter values")
            return

        updated = False

        for entry in meter_values:
            sampled_values = entry.get("sampledValue", [])
            
            for sample in sampled_values:
                try:
                    measurand = sample.get("measurand")
                    value_str = sample.get("value")
                    
                    # Skip empty or missing values
                    if not value_str:
                        continue
                    
                    # Convert to float
                    value = float(value_str)
                    
                    # Process based on measurand type
                    if measurand == "Power.Active.Import":
                        if self.power != value:
                            self.power = value
                            updated = True
                            _LOGGER.debug("Power updated: %.1f W", value)
                            
                    elif measurand == "Energy.Active.Import.Register":
                        if self.energy != value:
                            self.energy = value
                            updated = True
                            _LOGGER.debug("Energy updated: %.3f Wh", value)
                    
                except (ValueError, TypeError) as e:
                    _LOGGER.warning(
                        "Failed to parse meter value (measurand=%s, value=%s): %s",
                        sample.get("measurand"),
                        sample.get("value"),
                        e
                    )
                    continue
                    
                except Exception as e:
                    _LOGGER.error(
                        "Unexpected error processing meter sample %s: %s",
                        sample,
                        e,
                        exc_info=True
                    )
                    continue

        if updated:
            _LOGGER.debug("Meter values processed successfully")

