import logging
from datetime import datetime, timezone, time

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
        self._external_limit_power = 10.0
        self.external_limit_power_enable = None
        self.charger_mode = None
        self.server_url = None

        # Auto charge times (Thor values)
        self.auto_charge_start_time = None
        self.auto_charge_stop_time = None

        # Auto charge times (pending UI values)
        self.auto_charge_start_time_pending = None
        self.auto_charge_stop_time_pending = None

        # ── Laatste sessie ─────────────────
        self.last_session_energy = None
        self.last_session_cost = None
        self.charge_mode = None
        self.work_mode = None

        # ── External meter (grid connection) ───
        self.grid_power = None
        self.grid_voltages = {}
        self.grid_currents = {}
        self.wiring_type = None

        # 🆕 SESSION HISTORY (laatste 5 sessies)
        self.session_history = []

    # ─────────────────────────────
    # 🔑 LOAD BALANCING PROPERTY
    # ─────────────────────────────

    @property
    def external_limit_power(self):
        """Return current load balancing limit (kW)."""
        return self._external_limit_power

    @external_limit_power.setter
    def external_limit_power(self, value):
        """Update load balancing limit."""
        self._external_limit_power = float(value)
        _LOGGER.debug("Load balancing limit updated to: %.1f kW", self._external_limit_power)

    # ─────────────────────────────
    # Utility methods
    # ─────────────────────────────

    def now(self) -> str:
        """Return current UTC timestamp in ISO format."""
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

        # 🆕 RESET energy bij START nieuwe sessie
        _LOGGER.info("🔋 New transaction started → Resetting energy counter")
        self.energy = 0

        _LOGGER.info("Transaction started: %s (idTag=%s)", transaction_id, id_tag)
        self.async_set_updated_data(True)


    def stop_transaction(self, reason=None):
        """Stop charging transaction."""
        _LOGGER.info("Transaction stopped: %s (reason=%s)", self.transaction_id, reason)

        # 🆕 RESET alle charge-waarden NA stop
        _LOGGER.info("🛑 Transaction stopped → Resetting charge values")
        self.power = 0
        self.currents = {"L1": 0, "L2": 0, "L3": 0}
        self.voltages = {"L1": 0, "L2": 0, "L3": 0}
        self.phase_power = {"L1": 0, "L2": 0, "L3": 0}
        # energy blijft staan tot nieuwe sessie start!

        self.transaction_id = None
        self.status = "Idle"
        self.async_set_updated_data(True)

    # ─────────────────────────────
    # MeterValues
    # ─────────────────────────────

    def process_meter_values(self, meter_values):
        """Process meter values with TIER 1 error handling."""
        _LOGGER.info("🔵 process_meter_values called with %d entries", len(meter_values))
        updated = False

        try:
            for idx, entry in enumerate(meter_values):
                _LOGGER.debug("  Entry %d type: %s", idx, type(entry))

                sampled_values = None
                if hasattr(entry, 'sampled_value'):
                    sampled_values = entry.sampled_value
                    _LOGGER.debug("  → Using entry.sampled_value (attribute)")
                elif isinstance(entry, dict) and 'sampled_value' in entry:
                    sampled_values = entry['sampled_value']
                    _LOGGER.debug("  → Using entry['sampled_value'] (dict, underscore)")
                elif isinstance(entry, dict) and 'sampledValue' in entry:
                    sampled_values = entry['sampledValue']
                    _LOGGER.debug("  → Using entry['sampledValue'] (dict, camelCase)")
                else:
                    _LOGGER.warning("  ⚠️ Cannot find sampledValue in entry keys: %s", list(entry.keys()) if isinstance(entry, dict) else 'not a dict')
                    continue

                if not sampled_values:
                    _LOGGER.warning("  ⚠️ sampled_values is empty")
                    continue

                _LOGGER.info("  → Processing %d samples", len(sampled_values))

                for sample in sampled_values:
                    try:
                        value_str = None
                        measurand = None
                        phase = None

                        if hasattr(sample, 'value'):
                            value_str = sample.value
                            measurand = sample.measurand
                            phase = getattr(sample, 'phase', None)
                        elif isinstance(sample, dict):
                            value_str = sample.get("value")
                            measurand = sample.get("measurand")
                            phase = sample.get("phase")
                        else:
                            _LOGGER.warning("    ⚠️ Unknown sample type: %s", type(sample))
                            continue

                        if not value_str:
                            continue

                        value = float(value_str)

                    except (TypeError, ValueError, AttributeError) as e:
                        _LOGGER.warning("    Failed to parse sample: %s", e)
                        continue

                    if measurand == "Energy.Active.Import.Register":
                        if self.energy != value:
                            self.energy = value
                            _LOGGER.info("    ✅ Energy: %.3f Wh", value)
                            updated = True

                    elif measurand == "Power.Active.Import" and phase:
                        if self.phase_power.get(phase) != value:
                            self.phase_power[phase] = value
                            _LOGGER.info("    ✅ Power %s: %.1f W", phase, value)
                            updated = True

                    elif measurand == "Current.Import" and phase:
                        if self.currents.get(phase) != value:
                            self.currents[phase] = value
                            _LOGGER.info("    ✅ Current %s: %.2f A", phase, value)
                            updated = True

                    elif measurand == "Voltage" and phase:
                        if self.voltages.get(phase) != value:
                            self.voltages[phase] = value
                            _LOGGER.info("    ✅ Voltage %s: %.1f V", phase, value)
                            updated = True

                    elif measurand == "Temperature":
                        if self.temperature != value:
                            self.temperature = value
                            _LOGGER.info("    ✅ Temperature: %.1f °C", value)
                            updated = True

            if self.phase_power:
                total = sum(self.phase_power.values())
                if self.power != total:
                    self.power = total
                    _LOGGER.info("  ✅ Total power: %.1f W", total)
                    updated = True

            if updated:
                _LOGGER.info("🔄 Notifying sensors...")
                self.async_set_updated_data(True)
            else:
                _LOGGER.warning("⚠️ No updates from MeterValues")

        except Exception as exc:
            _LOGGER.error("💥 CRASH in process_meter_values: %s", exc, exc_info=True)

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
                        _LOGGER.debug("Config: ExternalLimitPower = %.1f kW", value)
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

                elif key == "G_AutoChargeTime":
                    if "-" in raw:
                        start_str, stop_str = raw.split("-", 1)
                        try:
                            start_time = datetime.strptime(start_str.strip(), "%H:%M").time()
                            stop_time = datetime.strptime(stop_str.strip(), "%H:%M").time()

                            if self.auto_charge_start_time != start_time:
                                self.auto_charge_start_time = start_time
                                self.auto_charge_start_time_pending = start_time
                                _LOGGER.debug("Config: AutoChargeStartTime = %s", start_time)
                                updated = True

                            if self.auto_charge_stop_time != stop_time:
                                self.auto_charge_stop_time = stop_time
                                self.auto_charge_stop_time_pending = stop_time
                                _LOGGER.debug("Config: AutoChargeStopTime = %s", stop_time)
                                updated = True
                        except ValueError as exc:
                            _LOGGER.warning("Failed to parse G_AutoChargeTime '%s': %s", raw, exc)

            except (ValueError, TypeError) as exc:
                _LOGGER.warning("Failed to parse config key=%s value=%s: %s", key, raw, exc)
                continue

            except Exception as exc:
                _LOGGER.error("Unexpected error processing config key=%s: %s", key, exc, exc_info=True)
                continue

        if updated:
            self.async_set_updated_data(True)

    # ─────────────────────────────
    # 🆕 Growatt frozenrecord (met session history)
    # ─────────────────────────────

    def process_frozen_record(self, data: dict):
        """Process Growatt frozen record with session history."""
        try:
            session = {
                "timestamp": self.now(),
                "energy_kwh": float(data.get("costenergy", 0)) / 1000,
                "cost": float(data.get("costmoney", 0)) / 100,
                "charge_mode": data.get("chargemode", ""),
                "work_mode": data.get("workmode", ""),
                "plug_time": data.get("plugtime", ""),
                "unplug_time": data.get("unplugtime", ""),
                "start_time": data.get("starttime", ""),
                "end_time": data.get("endtime", ""),
                "transaction_id": data.get("transactionId", ""),
            }
            
            # Backwards compatibility
            self.last_session_energy = session["energy_kwh"]
            self.last_session_cost = session["cost"]
            self.charge_mode = session["charge_mode"]
            self.work_mode = session["work_mode"]
            
            # 🆕 Session history (laatste 5)
            self.session_history.insert(0, session)
            if len(self.session_history) > 5:
                self.session_history = self.session_history[:5]
            
            _LOGGER.info(
                "Frozen record: energy=%.3f kWh, cost=%.2f, mode=%s/%s (saved to history)",
                session["energy_kwh"],
                session["cost"],
                session["charge_mode"],
                session["work_mode"]
            )
            
            self.async_set_updated_data(True)

        except (ValueError, TypeError, KeyError) as exc:
            _LOGGER.warning("Failed to process frozen record %s: %s", data, exc)

    # ─────────────────────────────
    # Growatt external meter values
    # ─────────────────────────────

    def process_external_meter(self, data_str: str):
        """Process external meter values from get_external_meterval DataTransfer."""
        try:
            pairs = data_str.split("&")
            values = {}
            for pair in pairs:
                if "=" in pair:
                    key, val = pair.split("=", 1)
                    values[key] = val

            updated = False

            if "wring" in values:
                try:
                    wiring = int(values["wring"])
                    if self.wiring_type != wiring:
                        self.wiring_type = wiring
                        updated = True
                        _LOGGER.debug("Wiring type: %s", "3-phase" if wiring == 1 else "1-phase")
                except ValueError:
                    pass

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
            _LOGGER.warning("Failed to process external meter data '%s': %s", data_str, exc)

