import logging
from datetime import datetime

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class GrowattCoordinator(DataUpdateCoordinator):
    """Coordinator voor Growatt THOR OCPP data."""

    def __init__(self, hass):
        super().__init__(hass, _LOGGER, name="Growatt THOR Coordinator")

        # Identiteit
        self.charge_point_id = None

        # Status / transactie
        self.status = None
        self.transaction_id = None
        self.id_tag = None

        # Live meting
        self.power = None       # W
        self.energy = None      # Wh

        # Laatste sessie (Growatt frozenrecord)
        self.last_session_energy = None   # Wh
        self.last_session_cost = None     # cent?
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
                measurand = sample.get("measurand")
                try:
                    value = float(sample.get("value"))
                except Exception:
                    continue

                if measurand == "Power.Active.Import":
                    self.power = value
                    updated = True
                elif measurand == "Energy.Active.Import.Register":
                    self.energy = value
                    updated = True

        if updated:
            self.async_set_updated_data(True)

    # ─────────────────────────────
    # Growatt frozenrecord
    # ─────────────────────────────

    def process_frozen_record(self, data: dict):
        _LOGGER.info("Processing frozenrecord data")

        self.last_session_energy = float(data.get("costenergy", 0))
        self.last_session_cost = float(data.get("costmoney", 0))
        self.charge_mode = data.get("chargemode")
        self.work_mode = data.get("workmode")

        _LOGGER.info(
            "Last session: energy=%sWh cost=%s mode=%s workmode=%s",
            self.last_session_energy,
            self.last_session_cost,
            self.charge_mode,
            self.work_mode,
        )

        self.async_set_updated_data(True)

