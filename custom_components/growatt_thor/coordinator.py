import logging
from datetime import datetime

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

    # ─────────────────────────────

    def now(self) -> str:
        return datetime.utcnow().isoformat() + "Z"

    def set_charge_point(self, cp_id):
        self.charge_point_id = cp_id
        self.async_set_updated_data(True)

    def set_status(self, status):
        value = status.value if hasattr(status, "value") else str(status)
        if self.status != value:
            self.status = value
            self.async_set_updated_data(True)

    def start_transaction(self, transaction_id, id_tag=None):
        self.transaction_id = transaction_id
        self.id_tag = id_tag
        self.status = "Charging"
        self.async_set_updated_data(True)

    def stop_transaction(self, reason=None):
        self.transaction_id = None
        self.status = "Idle"
        self.async_set_updated_data(True)

    # ─────────────────────────────
    # MeterValues
    # ─────────────────────────────

    def process_meter_values(self, meter_values):
        updated = False

        for entry in meter_values:
            for sample in entry.get("sampledValue", []):
                try:
                    value = float(sample.get("value"))
                except (TypeError, ValueError):
                    continue

                measurand = sample.get("measurand")
                phase = sample.get("phase")

                # Energie totaal
                if measurand == "Energy.Active.Import.Register":
                    if self.energy != value:
                        self.energy = value
                        updated = True

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

        if updated:
            self.async_set_updated_data(True)

    # ─────────────────────────────
    # GetConfiguration verwerking
    # ─────────────────────────────

    def process_configuration(self, configuration: list):
        updated = False

        for item in configuration:
            key = item.get("key")
            raw = item.get("value")

            try:
                if key == "G_MaxCurrent":
                    value = float(raw)
                    if self.max_current != value:
                        self.max_current = value
                        updated = True

                elif key == "G_ExternalLimitPower":
                    value = float(raw)
                    if self.external_limit_power != value:
                        self.external_limit_power = value
                        updated = True

                elif key == "G_ExternalLimitPowerEnable":
                    value = raw in ("1", "true", "True")
                    if self.external_limit_power_enable != value:
                        self.external_limit_power_enable = value
                        updated = True

                elif key == "G_ChargerMode":
                    value = int(raw)
                    if self.charger_mode != value:
                        self.charger_mode = value
                        updated = True

                elif key == "G_ServerURL":
                    if self.server_url != raw:
                        self.server_url = raw
                        updated = True

            except Exception as exc:
                _LOGGER.warning("Failed to parse config %s=%s (%s)", key, raw, exc)

        if updated:
            self.async_set_updated_data(True)

    # ─────────────────────────────
    # Growatt frozenrecord
    # ─────────────────────────────

    def process_frozen_record(self, data: dict):
        self.last_session_energy = float(data.get("costenergy", 0))
        self.last_session_cost = float(data.get("costmoney", 0))
        self.charge_mode = data.get("chargemode")
        self.work_mode = data.get("workmode")
        self.async_set_updated_data(True)

