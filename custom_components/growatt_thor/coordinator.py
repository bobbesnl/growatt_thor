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

        # Extra dynamische data voor sensoren
        # key: parameternaam
        # value: dict met units, icon en eventueel displaynaam
        self.extra_data: dict[str, dict] = {
            # MeterValues
            "current": {"unit": "A", "icon": "mdi:current-ac"},
            "voltage": {"unit": "V", "icon": "mdi:flash"},
            # Vendor / DataTransfer
            "max_current": {"unit": "A", "icon": "mdi:current-dc"},
            "max_power": {"unit": "W", "icon": "mdi:flash"},
            "mode": {"unit": None, "icon": "mdi:remote"},
            "lcd": {"unit": None, "icon": "mdi:screen"},
            # Autorisatie / IdTag
            "id_tag": {"unit": None, "icon": "mdi:card-account-details"},
            # Transaction info
            "transaction_id": {"unit": None, "icon": "mdi:counter"},
            "meter_start": {"unit": "Wh", "icon": "mdi:counter"},
            "meter_stop": {"unit": "Wh", "icon": "mdi:counter"},
            "reason": {"unit": None, "icon": "mdi:alert"},
        }

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

    def start_transaction(self, transaction_id: int, meter_start: float = 0, id_tag: str | None = None) -> None:
        _LOGGER.info("Transaction started: %s", transaction_id)
        self.transaction_id = transaction_id
        self.status = "Charging"
        self.extra_data["transaction_id"] = transaction_id
        self.extra_data["meter_start"] = meter_start
        self.extra_data["id_tag"] = id_tag
        self.async_set_updated_data(True)

    def stop_transaction(self, meter_stop: float = 0, reason: str | None = None) -> None:
        _LOGGER.info("Transaction stopped")
        self.transaction_id = None
        self.status = "Idle"
        self.extra_data["meter_stop"] = meter_stop
        self.extra_data["reason"] = reason
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
                    self.extra_data["power"] = value
                elif measurand == "Energy.Active.Import.Register":
                    self.energy = value
                    updated = True
                    self.extra_data["energy"] = value
                elif measurand == "Current.Import":
                    self.extra_data["current"] = value
                    updated = True
                elif measurand == "Voltage":
                    self.extra_data["voltage"] = value
                    updated = True

        if updated:
            _LOGGER.debug(
                "Meter update: power=%s W energy=%s Wh",
                self.power,
                self.energy,
            )
            self.async_set_updated_data(True)

    # ─────────────────────────────
    # Vendor / DataTransfer
    # ─────────────────────────────
    def process_data_transfer(self, vendor_data: dict) -> None:
        for key in ["maxCurrent", "maxPower", "mode", "lcd"]:
            if key in vendor_data:
                self.extra_data[key.lower()] = vendor_data[key]
        self.async_set_updated_data(True)

