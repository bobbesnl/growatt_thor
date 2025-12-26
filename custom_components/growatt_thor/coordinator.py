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

        # Live metingen
        self.power = None       # W
        self.energy = None      # Wh

	# Fase-specifiek live metingen (worden iedere 2 minuten vertuurd vanuit THOR tijdens laden)
	self.current_l1 = None
	self.current_l2 = None
	self.current_l3 = None

	self.voltage_l1 = None
	self.voltage_l2 = None
	self.voltage_l3 = None

	self.power_l1 = None
	self.power_l2 = None
	self.power_l3 = None

	self.temperature = None


        # Config (beperkt, bewust)
        self.max_current = None                     # G_MaxCurrent
        self.external_limit_power = None            # G_ExternalLimitPower
        self.external_limit_power_enable = None     # G_ExternalLimitPowerEnable
        self.charger_mode = None                    # G_ChargerMode
        self.server_url = None                      # G_ServerURL

        # Laatste sessie
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
            _LOGGER.info("Status changed: %s → %s", self.status, value)
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
                except Exception:
                    continue

                measurand = sample.get("measurand")
                phase = sample.get("phase")

                # Energie (totaal)
                if measurand == "Energy.Active.Import.Register":
                    if self.energy != value:
                        self.energy = value
                        updated = True

                # Vermogen per fase
                elif measurand == "Power.Active.Import":
                    if phase == "L1" and self.power_l1 != value:
                        self.power_l1 = value
                        updated = True
                    elif phase == "L2" and self.power_l2 != value:
                        self.power_l2 = value
                        updated = True
                    elif phase == "L3" and self.power_l3 != value:
                        self.power_l3 = value
                        updated = True

                # Stroom per fase
                elif measurand == "Current.Import":
                    if phase == "L1" and self.current_l1 != value:
                        self.current_l1 = value
                        updated = True
                    elif phase == "L2" and self.current_l2 != value:
                        self.current_l2 = value
                        updated = True
                    elif phase == "L3" and self.current_l3 != value:
                        self.current_l3 = value
                        updated = True

                # Spanning per fase
                elif measurand == "Voltage":
                    if phase == "L1" and self.voltage_l1 != value:
                        self.voltage_l1 = value
                        updated = True
                    elif phase == "L2" and self.voltage_l2 != value:
                        self.voltage_l2 = value
                        updated = True
                    elif phase == "L3" and self.voltage_l3 != value:
                        self.voltage_l3 = value
                        updated = True

                # Temperatuur
                elif measurand == "Temperature":
                    if self.temperature != value:
                        self.temperature = value
                        updated = True

        if updated:
            self.async_set_updated_data(True)


    # ─────────────────────────────
    #  GetConfiguration verwerking (beperkt)
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
            _LOGGER.info("Growatt configuration updated")
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

