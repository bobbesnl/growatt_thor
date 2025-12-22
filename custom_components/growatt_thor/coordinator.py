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

        # ─────────────────────────────
        # Basis attributen
        # ─────────────────────────────
        self.charge_point_id: str | None = None
        self.status: str | None = None
        self.transaction_id: int | None = None
        self.connectorId: int | None = None
        self.idTag: str | None = None
        self.meterStart: float | None = None
        self.meterStop: float | None = None
        self.startReason: str | None = None
        self.stopReason: str | None = None
        self.errorCode: str | None = None

        # MeterValues
        self.Power_Active_Import: float | None = None
        self.Energy_Active_Import_Register: float | None = None
        self.Current_Import: float | None = None
        self.Voltage: float | None = None

        # Boot & connectie
        self.chargePointVendor: str | None = None
        self.chargePointModel: str | None = None
        self.firmwareVersion: str | None = None
        self.serialNumber: str | None = None

        # Vendor-specifiek (DataTransfer)
        self.vendor_data: dict = {}

    # ─────────────────────────────
    # Helpers
    # ─────────────────────────────
    def now(self) -> str:
        """UTC timestamp in OCPP formaat."""
        return datetime.utcnow().isoformat() + "Z"

    def _set_and_update(self, attr, value):
        if getattr(self, attr, None) != value:
            setattr(self, attr, value)
            self.async_set_updated_data(True)

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
    def set_status(self, status: str | object) -> None:
        value = status.value if hasattr(status, "value") else str(status)
        if self.status != value:
            _LOGGER.info("Status changed to %s", value)
        self.status = value
        self.async_set_updated_data(True)

    def start_transaction(self, transaction_id: int, connectorId=None, idTag=None, meterStart=None) -> None:
        _LOGGER.info("Transaction started: %s", transaction_id)
        self.transaction_id = transaction_id
        self.status = "Charging"
        self.connectorId = connectorId
        self.idTag = idTag
        self.meterStart = meterStart
        self.async_set_updated_data(True)

    def stop_transaction(self, meterStop=None, reason=None) -> None:
        _LOGGER.info("Transaction stopped")
        self.transaction_id = None
        self.status = "Idle"
        self.meterStop = meterStop
        self.stopReason = reason
        self.async_set_updated_data(True)

    # ─────────────────────────────
    # Metering
    # ─────────────────────────────
    def process_meter_values(self, meter_values: list) -> None:
        updated = False
        for entry in meter_values:
            for sample in entry.get("sampledValue", []):
                measurand = sample.get("measurand", "").replace(".", "_")
                value = sample.get("value")
                if value is None:
                    continue
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    pass
                if hasattr(self, measurand):
                    setattr(self, measurand, value)
                    updated = True
        if updated:
            _LOGGER.debug(
                "Meter update: Power=%s W, Energy=%s Wh, Current=%s A, Voltage=%s V",
                self.Power_Active_Import,
                self.Energy_Active_Import_Register,
                self.Current_Import,
                self.Voltage,
            )
            self.async_set_updated_data(True)

    # ─────────────────────────────
    # Boot / connectie
    # ─────────────────────────────
    def set_boot_info(self, vendor=None, model=None, firmware=None, serial=None):
        self._set_and_update("chargePointVendor", vendor)
        self._set_and_update("chargePointModel", model)
        self._set_and_update("firmwareVersion", firmware)
        self._set_and_update("serialNumber", serial)

    # ─────────────────────────────
    # Vendor-specific (Growatt)
    # ─────────────────────────────
    def set_vendor_data(self, vendor_data: dict):
        if not isinstance(vendor_data, dict):
            return
        self.vendor_data.update(vendor_data)
        self.async_set_updated_data(True)

