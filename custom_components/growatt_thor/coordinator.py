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

        self.charge_point_id: str | None = None
        self.status: str | None = None
        self.power: float | None = None
        self.energy: float | None = None
        self.transaction_id: int | None = None

    # ─────────────────────────────
    # Helpers
    # ─────────────────────────────

    def now(self) -> str:
        """UTC timestamp in OCPP formaat."""
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

    def start_transaction(self, transaction_id: int) -> None:
        _LOGGER.info("Transaction started: %s", transaction_id)

        self.transaction_id = transaction_id
        self.status = "Charging"
        self.async_set_updated_data(True)

    def stop_transaction(self) -> None:
        _LOGGER.info("Transaction stopped")

        self.transaction_id = None
        self.status = "Idle"
        self.async_set_updated_data(True)

    # ─────────────────────────────
    # Metering
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

        if updated:
            _LOGGER.debug(
                "Meter update: power=%s W energy=%s Wh",
                self.power,
                self.energy,
            )
            self.async_set_updated_data(True)

