import logging
from datetime import datetime, timezone

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class GrowattCoordinator(DataUpdateCoordinator):
    """Coordinator voor Growatt THOR OCPP data."""

    def __init__(self, hass):
        super().__init__(hass, _LOGGER, name="Growatt THOR Coordinator")

        self.charge_point_id = None
        self.status = None
        self.transaction_id = None
        self.id_tag = None

        # ── Totaal ─────────────────────────
        self.power = None        # W (som van fases)
        self.energy = None       # Wh

        # ── Fase-specifiek ─────────────────
        self.currents = {}       # {"L1": A, "L2": A, "L3": A}
        self.voltages = {}       # {"L1": V, "L2": V, "L3": V}
        self.phase_power = {}    # {"L1": W, "L2": W, "L3": W}

        self.temperature = None  # °C

        # ── Config (Growatt) ───────────────
        self.max_current = None
        self.external_limit_power = None
        self.external_limit_power_enable = None
        self.charger_mode = None
        self.server_url = None

        # ── Laatste sessie ─────────────────
        self.last_session_energy = None
        self.last_session_cost = None
        self.charge_mode = None
        self.work_mode = None

        # ── External meter (grid connection) ───
        self.grid_power = None          # W (netto huisverbruik)
        self.grid_voltages = {}         # {"L1": V, "L2": V, "L3": V}
        self.grid_currents = {}         # {"L1": A, "L2": A, "L3": A}
        self.wiring_type = None         # 1 = 3-fase, 0 = 1-fase

    # ─────────────────────────────

    def now(self) -> str:
        """Return current UTC timestamp in ISO format.

        TIER 1 FIX: Use timezone-aware datetime.now() instead of deprecated utcnow()
        """
        return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')

    def set_charge_point(self, cp_id):
        """Set charge point ID and notify sensors."""
        if self.charge_point_id != cp_id:
            self.charge_point_id = cp_id
            _LOGGER.info("Charge point connected: %s", cp_id)
        self.async_set_updated_data(True)

    def set_status(self, status):
        """Set charger status and notify sensors."""
        value = status.value if hasattr(status, "value") else str(status)
        if self.status != value:
            self.status = value
            _LOGGER.debug("Status changed to: %s", value)
        self.async_set_updated_data(True)

    def start_transaction(self, transaction_id, id_tag=None):
        """Start charging transaction."""
        self.transaction_id = transaction_id
        self.id_tag = id_tag
        self.status = "Charging"
        _LOGGER.info("Transaction started: %s (idTag=%s)", transaction_id, id_tag)
        self.async_set_updated_data(True)

    def stop_transaction(self, reason=None):
        """Stop charging transaction."""
        _LOGGER.info("Transaction stopped: %s (reason=%s)", self.transaction_id, reason)
        self.transaction_id = None
        self.status = "Idle"
        self.async_set_updated_data(True)

    # ─────────────────────────────
    # MeterValues
    # ─────────────────────────────

    def process_meter_values(self, meter_values):
        """Process meter values with TIER 1 error handling."""
        _LOGGER.info("🔍 Received MeterValues with %d entries (type: %s)", len(meter_values), type(meter_values))
        updated = False

        for idx, entry in enumerate(meter_values):
            _LOGGER.debug("  Processing entry %d (type: %s)", idx, type(entry))
            
            # OCPP library gebruikt objecten, niet dicts
            # Probeer eerst attribute access, dan dict access
            sampled_values = getattr(entry, 'sampled_value', None)
            if sampled_values is None:
                sampled_values = entry.get("sampledValue", [])
            
            _LOGGER.info("  → Found %d sampled values in entry %d", len(sampled_values), idx)
            
            for sample_idx, sample in enumerate(sampled_values):
                try:
                    # Ook sample kan een object zijn
                    value_str = getattr(sample, 'value', None)
                    if value_str is None:
                        value_str = sample.get("value")
                    
                    measurand = getattr(sample, 'measurand', None)
                    if measurand is None:
                        measurand = sample.get("measurand")
                    
                    phase = getattr(sample, 'phase', None)
                    if phase is None:
                        phase = sample.get("phase")
                    
                    unit = getattr(sample, 'unit', None)
                    if unit is None:
                        unit = sample.get("unit")

                    _LOGGER.debug("    Sample %d: measurand=%s phase=%s value=%s unit=%s", 
                                 sample_idx, measurand, phase, value_str, unit)

                    # TIER 1 FIX: Skip empty values
                    if not value_str:
                        _LOGGER.warning("    ⚠️ Empty value for measurand=%s", measurand)
                        continue

                    value = float(value_str)

                except (TypeError, ValueError) as e:
                    # TIER 1 FIX: Log parsing errors without crashing
                    _LOGGER.warning(
                        "Failed to parse meter value (measurand=%s, value=%s): %s",
                        measurand,
                        value_str,
                        e
                    )
                    continue

                # Energie totaal
                if measurand == "Energy.Active.Import.Register":
                    if self.energy != value:
                        _LOGGER.info("✅ Energy updated: %.3f Wh (was: %s)", value, self.energy)
                        self.energy = value
                        updated = True

                # Vermogen per fase
                elif measurand == "Power.Active.Import" and phase:
                    if self.phase_power.get(phase) != value:
                        _LOGGER.info("✅ Power %s updated: %.1f W (was: %s)", phase, value, self.phase_power.get(phase))
                        self.phase_power[phase] = value
                        updated = True

                # Stroom per fase
                elif measurand == "Current.Import" and phase:
                    if self.currents.get(phase) != value:
                        _LOGGER.info("✅ Current %s updated: %.2f A (was: %s)", phase, value, self.currents.get(phase))
                        self.currents[phase] = value
                        updated = True

                # Spanning per fase
                elif measurand == "Voltage" and phase:
                    if self.voltages.get(phase) != value:
                        _LOGGER.info("✅ Voltage %s updated: %.1f V (was: %s)", phase, value, self.voltages.get(phase))
                        self.voltages[phase] = value
                        updated = True

                # Temperatuur
                elif measurand == "Temperature":
                    if self.temperature != value:
                        _LOGGER.info("✅ Temperature updated: %.1f °C (was: %s)", value, self.temperature)
                        self.temperature = value
                        updated = True

        # Totaal vermogen = som fases
        if self.phase_power:
            total = sum(self.phase_power.values())
            if self.power != total:
                _LOGGER.info("✅ Total power calculated: %.1f W (was: %s)", total, self.power)
                self.power = total
                updated = True

        if updated:
            _LOGGER.info("🔄 Coordinator updated - notifying %d listeners", len(self._listeners))
            self.async_set_updated_data(True)
        else:
            _LOGGER.warning("⚠️ No sensor updates from MeterValues")

    # ─────────────────────────────
    # GetConfiguration verwerking
    # ─────────────────────────────

    def process_configuration(self, configuration: list):
        """Process GetConfiguration response with TIER 1 error handling."""
        updated = False

        for item in configuration:
            key = item.get("key")
            raw = item.get("value")

            try:
                if key == "G_MaxCurrent":
                    value = float(raw)
                    if self.max_current != value:
                        self.max_current = value
                        _LOGGER.debug("Config: MaxCurrent = %.1f A", value)
                        updated = True

                elif key == "G_ExternalLimitPower":
                    value = float(raw)
                    if self.external_limit_power != value:
                        self.external_limit_power = value
                        _LOGGER.debug("Config: ExternalLimitPower = %.1f W", value)
                        updated = True

                elif key == "G_ExternalLimitPowerEnable":
                    value = raw in ("1", "true", "True")
                    if self.external_limit_power_enable != value:
                        self.external_limit_power_enable = value
                        _LOGGER.debug("Config: ExternalLimitPowerEnable = %s", value)
                        updated = True

                elif key == "G_ChargerMode":
                    value = int(raw)
                    if self.charger_mode != value:
                        self.charger_mode = value
                        _LOGGER.debug("Config: ChargerMode = %d", value)
                        updated = True

                elif key == "G_ServerURL":
                    if self.server_url != raw:
                        self.server_url = raw
                        _LOGGER.debug("Config: ServerURL = %s", raw)
                        updated = True

            except (ValueError, TypeError) as exc:
                # TIER 1 FIX: Better error logging with context
                _LOGGER.warning(
                    "Failed to parse config key=%s value=%s: %s",
                    key,
                    raw,
                    exc
                )
                continue

            except Exception as exc:
                # TIER 1 FIX: Catch unexpected errors
                _LOGGER.error(
                    "Unexpected error processing config key=%s: %s",
                    key,
                    exc,
                    exc_info=True
                )
                continue

        if updated:
            self.async_set_updated_data(True)

    # ─────────────────────────────
    # Growatt frozenrecord
    # ─────────────────────────────

    def process_frozen_record(self, data: dict):
        """Process Growatt frozen record with TIER 1 error handling."""
        try:
            self.last_session_energy = float(data.get("costenergy", 0))
            self.last_session_cost = float(data.get("costmoney", 0))
            self.charge_mode = data.get("chargemode")
            self.work_mode = data.get("workmode")

            _LOGGER.info(
                "Frozen record: energy=%.3f kWh, cost=%.2f, mode=%s/%s",
                self.last_session_energy,
                self.last_session_cost,
                self.charge_mode,
                self.work_mode
            )

            self.async_set_updated_data(True)

        except (ValueError, TypeError, KeyError) as exc:
            # TIER 1 FIX: Graceful error handling
            _LOGGER.warning(
                "Failed to process frozen record %s: %s",
                data,
                exc
            )

    # ─────────────────────────────
    # Growatt external meter values
    # ─────────────────────────────

    def process_external_meter(self, data_str: str):
        """Process external meter values from get_external_meterval DataTransfer.

        Deze data komt van de externe meter (bijv. Eastron SDM630) en geeft
        informatie over de huisaansluiting (niet de laadinformatie).

        Args:
            data_str: Query string like "used=0&wring=1&u-voltage=230&power=1500"
        """
        try:
            # Parse query string
            pairs = data_str.split("&")
            values = {}
            for pair in pairs:
                if "=" in pair:
                    key, val = pair.split("=", 1)
                    values[key] = val

            updated = False

            # Wiring type (1 = 3-phase, 0 = 1-phase)
            if "wring" in values:
                try:
                    wiring = int(values["wring"])
                    if self.wiring_type != wiring:
                        self.wiring_type = wiring
                        updated = True
                        _LOGGER.debug("Wiring type: %s", "3-phase" if wiring == 1 else "1-phase")
                except ValueError:
                    pass

            # Grid voltages (per fase)
            for phase_key, phase_name in [("u-voltage", "L1"), ("v-voltage", "L2"), ("w-voltage", "L3")]:
                if phase_key in values:
                    try:
                        voltage = float(values[phase_key])
                        if self.grid_voltages.get(phase_name) != voltage:
                            self.grid_voltages[phase_name] = voltage
                            updated = True
                            _LOGGER.debug("Grid voltage %s: %.1f V", phase_name, voltage)
                    except ValueError:
                        pass

            # Grid currents (per fase)
            for phase_key, phase_name in [("u-current", "L1"), ("v-current", "L2"), ("w-current", "L3")]:
                if phase_key in values:
                    try:
                        current = float(values[phase_key])
                        if self.grid_currents.get(phase_name) != current:
                            self.grid_currents[phase_name] = current
                            updated = True
                            _LOGGER.debug("Grid current %s: %.1f A", phase_name, current)
                    except ValueError:
                        pass

            # Grid power (total)
            if "power" in values:
                try:
                    power = float(values["power"])
                    if self.grid_power != power:
                        self.grid_power = power
                        updated = True
                        _LOGGER.debug("Grid power: %.1f W", power)
                except ValueError:
                    pass

            if updated:
                _LOGGER.info("External meter values processed successfully")
                self.async_set_updated_data(True)

        except (ValueError, TypeError, KeyError) as exc:
            _LOGGER.warning(
                "Failed to process external meter data '%s': %s",
                data_str,
                exc
            )

