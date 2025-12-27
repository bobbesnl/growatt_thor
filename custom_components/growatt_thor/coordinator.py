import logging
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class GrowattCoordinator(DataUpdateCoordinator):
    """Coordinator voor Growatt THOR OCPP data."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize coordinator.
        
        Args:
            hass: Home Assistant instance
        """
        super().__init__(hass, _LOGGER, name="Growatt THOR Coordinator")

        self.charge_point_id: Optional[str] = None
        self.status: Optional[str] = None
        self.transaction_id: Optional[int] = None
        self.id_tag: Optional[str] = None

        # ── Totaal ──────────────────────────────────────────
        self.power: Optional[float] = None        # W (som van fases)
        self.energy: Optional[float] = None       # Wh

        # ── Fase-specifiek ──────────────────────────────────
        self.currents: Dict[str, float] = {}       # {"L1": A, "L2": A, "L3": A}
        self.voltages: Dict[str, float] = {}       # {"L1": V, "L2": V, "L3": V}
        self.phase_power: Dict[str, float] = {}    # {"L1": W, "L2": W, "L3": W}

        self.temperature: Optional[float] = None  # °C

        # ── Config (Growatt) ────────────────────────────────
        self.max_current: Optional[float] = None
        self.external_limit_power: Optional[float] = None
        self.external_limit_power_enable: Optional[bool] = None
        self.charger_mode: Optional[int] = None
        self.server_url: Optional[str] = None

        # ── Laatste sessie ──────────────────────────────────
        self.last_session_energy: Optional[float] = None
        self.last_session_cost: Optional[float] = None
        self.charge_mode: Optional[str] = None
        self.work_mode: Optional[str] = None

        # ── Configuration cache ─────────────────────────────
        self.configuration_cache: Dict[str, Any] = {}

    # ──────────────────────────────────────────────────────
    # Utility Methods
    # ──────────────────────────────────────────────────────

    def now(self) -> str:
        """Get current UTC time in ISO format.
        
        Returns:
            ISO 8601 formatted timestamp with Z suffix
        """
        return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')

    def set_charge_point(self, cp_id: str) -> None:
        """Set charge point ID and update data.
        
        Args:
            cp_id: Charge point identifier
        """
        if self.charge_point_id != cp_id:
            self.charge_point_id = cp_id
            _LOGGER.info("Charge point set: %s", cp_id)
            self.async_set_updated_data(True)

    def set_status(self, status: Any) -> None:
        """Set charger status.
        
        Args:
            status: Status value (string or enum)
        """
        value = status.value if hasattr(status, "value") else str(status)
        if self.status != value:
            self.status = value
            _LOGGER.debug("Status changed: %s", value)
            self.async_set_updated_data(True)

    # ──────────────────────────────────────────────────────
    # Transaction Management
    # ──────────────────────────────────────────────────────

    def start_transaction(self, transaction_id: int, id_tag: Optional[str] = None) -> None:
        """Start a new charging transaction.
        
        Args:
            transaction_id: OCPP transaction ID
            id_tag: Optional RFID/card ID
        """
        self.transaction_id = transaction_id
        self.id_tag = id_tag
        self.status = "Charging"
        _LOGGER.info("Transaction started: %d (tag: %s)", transaction_id, id_tag)
        self.async_set_updated_data(True)

    def stop_transaction(self, reason: Optional[str] = None) -> None:
        """Stop the current charging transaction.
        
        Args:
            reason: Reason for stopping (e.g., 'Local', 'Remote', 'DeAuthorized')
        """
        _LOGGER.info("Transaction stopped: %d (reason: %s)", self.transaction_id, reason)
        self.transaction_id = None
        self.status = "Idle"
        self.async_set_updated_data(True)

    # ──────────────────────────────────────────────────────
    # Meter Values Processing
    # ──────────────────────────────────────────────────────

    def process_meter_values(self, meter_values: List[Dict[str, Any]]) -> None:
        """Process meter values from DataTransfer.
        
        Args:
            meter_values: List of meter value entries
        """
        updated = False

        for entry in meter_values:
            for sample in entry.get("sampledValue", []):
                try:
                    value = float(sample.get("value"))
                except (TypeError, ValueError) as e:
                    _LOGGER.debug("Failed to parse meter value: %s", e)
                    continue

                measurand = sample.get("measurand")
                phase = sample.get("phase")

                # Energie totaal
                if measurand == "Energy.Active.Import.Register":
                    if self.energy != value:
                        self.energy = value
                        updated = True
                        _LOGGER.debug("Energy: %.3f Wh", value)

                # Vermogen per fase
                elif measurand == "Power.Active.Import" and phase:
                    self.phase_power[phase] = value
                    updated = True

                # Stroom per fase
                elif measurand == "Current.Import" and phase:
                    self.currents[phase] = value
                    updated = True

                # Spanning per fase
                elif measurand == "Voltage" and phase:
                    self.voltages[phase] = value
                    updated = True

                # Temperatuur
                elif measurand == "Temperature":
                    if self.temperature != value:
                        self.temperature = value
                        updated = True

        # Totaal vermogen = som fases
        if self.phase_power:
            total = sum(self.phase_power.values())
            if self.power != total:
                self.power = total
                updated = True
                _LOGGER.debug("Total power: %.1f W", total)

        if updated:
            self.async_set_updated_data(True)

    # ──────────────────────────────────────────────────────
    # Configuration Processing
    # ──────────────────────────────────────────────────────

    def process_configuration(self, configuration: List[Dict[str, Any]]) -> None:
        """Process GetConfiguration response.
        
        Args:
            configuration: List of configuration key/value pairs
        """
        if not configuration:
            _LOGGER.warning("Received empty configuration list")
            return

        updated = False
        config_count = len(configuration)
        _LOGGER.info("Processing %d configuration keys", config_count)

        for item in configuration:
            try:
                key = item.get("key")
                raw = item.get("value")
                readonly = item.get("readonly", False)

                if not key:
                    _LOGGER.warning("Configuration item missing key: %s", item)
                    continue

                # Cache all config
                self.configuration_cache[key] = raw

                # Parse known keys
                if key == "G_MaxCurrent":
                    try:
                        value = float(raw)
                        if not (6 <= value <= 32):
                            _LOGGER.warning("G_MaxCurrent out of range: %s", value)
                        if self.max_current != value:
                            self.max_current = value
                            updated = True
                    except (TypeError, ValueError) as e:
                        _LOGGER.warning("Failed to parse G_MaxCurrent: %s (%s)", raw, e)

                elif key == "G_ExternalLimitPower":
                    try:
                        value = float(raw)
                        if self.external_limit_power != value:
                            self.external_limit_power = value
                            updated = True
                    except (TypeError, ValueError) as e:
                        _LOGGER.warning("Failed to parse G_ExternalLimitPower: %s (%s)", raw, e)

                elif key == "G_ExternalLimitPowerEnable":
                    value = raw in ("1", "true", "True", "enable", "Enable")
                    if self.external_limit_power_enable != value:
                        self.external_limit_power_enable = value
                        updated = True

                elif key == "G_ChargerMode":
                    try:
                        value = int(raw)
                        if self.charger_mode != value:
                            self.charger_mode = value
                            updated = True
                    except (TypeError, ValueError) as e:
                        _LOGGER.warning("Failed to parse G_ChargerMode: %s (%s)", raw, e)

                elif key == "G_ServerURL":
                    if self.server_url != raw:
                        self.server_url = raw
                        updated = True

                if key in ("G_MaxCurrent", "G_ExternalLimitPower", "G_ChargerMode", "G_ServerURL"):
                    _LOGGER.debug("Config %s = %s (readonly=%s)", key, raw, readonly)

            except Exception as exc:
                _LOGGER.error("Unexpected error processing config %s: %s", item.get("key"), exc, exc_info=True)

        if updated:
            _LOGGER.info("Configuration updated")
            self.async_set_updated_data(True)

    # ──────────────────────────────────────────────────────
    # Growatt Frozen Record
    # ──────────────────────────────────────────────────────

    def process_frozen_record(self, data: Dict[str, Any]) -> None:
        """Process frozenrecord from DataTransfer.
        
        Args:
            data: Parsed frozenrecord data
        """
        try:
            energy = float(data.get("costenergy", 0))
            cost = float(data.get("costmoney", 0))
            
            self.last_session_energy = energy
            self.last_session_cost = cost
            self.charge_mode = data.get("chargemode")
            self.work_mode = data.get("workmode")
            
            _LOGGER.info(
                "Frozen record: energy=%.3f Wh, cost=%.2f, mode=%s",
                energy, cost, self.charge_mode
            )
            self.async_set_updated_data(True)
        except Exception as exc:
            _LOGGER.error("Failed to process frozen record: %s", exc, exc_info=True)
