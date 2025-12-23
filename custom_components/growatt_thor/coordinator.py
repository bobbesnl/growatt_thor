import logging
from datetime import datetime

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class GrowattCoordinator(DataUpdateCoordinator):
    """Coordinator voor Growatt THOR OCPP data (push-based)."""

    def __init__(self, hass):
        super().__init__(
            hass,
            _LOGGER,
            name="Growatt THOR Coordinator",
        )

        # Identiteit
        self.charge_point_id: str | None = None

        # Status / transactie
        self.status: str | None = None
        self.transaction_id: int | None = None
        self.id_tag: str | None = None
        self.reason: str | None = None

        # Vermogen / energie
        self.power: float | None = None          # W
        self.energy: float | None = None         # Wh
        self.voltage: float | None = None        # V
        self.current: float | None = None        # A

        # Limieten / instellingen
        self.max_current: float | None = None    # A
        self.max_power: float | None = None      # W
        self.mode: str | None = None

        # UI / misc
        self.lcd: str | None = None

    # ─────────────────────────────
    # Helpers
    # ─────────────────────────────

    def now(self) -> str:
        return datetime.utcnow().isoformat() + "Z"

    # ─────────────────────────────
    # Charge point lifecycle
    # ─────────────────────────────

    def set_charge_point(self, cp_id: str) -> None:
        if self.charge_point_id != cp_id:
            _LOGGER.info("ChargePoint connected: %s", cp_id)

        self.charge_point_id = cp_id
        self.async_set_updated_data(True)

    # ─────────────────────────────
    # Status & transactions
    # ─────────────────────────────

    def set_status(self, status) -> None:
        value = status.value if hasattr(status, "value") else str(status)

        if self.status != value:
            _LOGGER.info("Status changed to %s", value)

        self.status = value
        self.async_set_updated_data(True)

    def start_transaction(self, transaction_id: int, id_tag: str | None = None) -> None:
        _LOGGER.info("Transaction started: %s", transaction_id)

        self.transaction_id = transaction_id
        self.id_tag = id_tag
        self.status = "Charging"
        self.async_set_updated_data(True)

    def stop_transaction(self, reason: str | None = None) -> None:
        _LOGGER.info("Transaction stopped (%s)", reason)

        self.transaction_id = None
        self.reason = reason
        self.status = "Idle"
        self.async_set_updated_data(True)

    # ─────────────────────────────
    # MeterValues
    # ─────────────────────────────

    def process_meter_values(self, meter_values: list) -> None:
        updated = False

        for entry in meter_values:
            for sample in entry.get("sampledValue", []):
                measurand = sample.get("measurand")
                value = sample.get("value")

                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue

                if measurand == "Power.Active.Import":
                    self.power = value
                    updated = True

                elif measurand == "Energy.Active.Import.Register":
                    self.energy = value
                    updated = True

                elif measurand == "Voltage":
                    self.voltage = value
                    updated = True

                elif measurand == "Current.Import":
                    self.current = value
                    updated = True

        if updated:
            _LOGGER.debug(
                "Meter update: P=%s W E=%s Wh V=%s V I=%s A",
                self.power,
                self.energy,
                self.voltage,
                self.current,
            )
            self.async_set_updated_data(True)

    # ─────────────────────────────
    # Config / instellingen (uit JSON dump)
    # ─────────────────────────────

    def set_limits(self, max_current: float | None = None, max_power: float | None = None):
        if max_current is not None:
            self.max_current = max_current
        if max_power is not None:
            self.max_power = max_power

        self.async_set_updated_data(True)

    def set_mode(self, mode: str):
        self.mode = mode
        self.async_set_updated_data(True)

    def set_lcd(self, text: str):
        self.lcd = text
        self.async_set_updated_data(True)

