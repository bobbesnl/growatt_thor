import logging
from datetime import datetime

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class GrowattCoordinator(DataUpdateCoordinator):
    """Coordinator voor Growatt THOR OCPP data (push-based + vendor specific)."""

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
        self.power: float | None = None      # W
        self.energy: float | None = None     # Wh
        self.voltage: float | None = None    # V
        self.current: float | None = None    # A

        # Limieten / instellingen (Growatt)
        self.max_current: float | None = None
        self.max_power: float | None = None
        self.mode: str | None = None
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
        else:
            _LOGGER.debug("ChargePoint %s already registered", cp_id)

    # ─────────────────────────────
    # Status & transactions
    # ─────────────────────────────

    def set_status(self, status) -> None:
        value = status.value if hasattr(status, "value") else str(status)

        if self.status != value:
            _LOGGER.info("Status changed: %s → %s", self.status, value)
            self.status = value
            self.async_set_updated_data(True)
        else:
            _LOGGER.debug("Status unchanged: %s", value)

    def start_transaction(self, transaction_id: int, id_tag: str | None = None) -> None:
        _LOGGER.info("Transaction started: %s", transaction_id)

        self.transaction_id = transaction_id
        self.id_tag = id_tag
        self.status = "Charging"
        self.async_set_updated_data(True)

    def stop_transaction(self, reason: str | None = None) -> None:
        _LOGGER.info("Transaction stopped (reason=%s)", reason)

        self.transaction_id = None
        self.reason = reason
        self.status = "Idle"
        self.async_set_updated_data(True)

    # ─────────────────────────────
    # MeterValues
    # ─────────────────────────────

    def process_meter_values(self, meter_values: list) -> None:
        updated = False

        _LOGGER.debug("Processing MeterValues: %s", meter_values)

        for entry in meter_values:
            for sample in entry.get("sampledValue", []):
                measurand = sample.get("measurand")
                try:
                    value = float(sample.get("value"))
                except (TypeError, ValueError):
                    _LOGGER.debug(
                        "Skipping invalid meter value: %s=%s",
                        measurand,
                        sample.get("value"),
                    )
                    continue

                if measurand == "Power.Active.Import":
                    if self.power != value:
                        self.power = value
                        updated = True

                elif measurand == "Energy.Active.Import.Register":
                    if self.energy != value:
                        self.energy = value
                        updated = True

                elif measurand == "Voltage":
                    if self.voltage != value:
                        self.voltage = value
                        updated = True

                elif measurand == "Current.Import":
                    if self.current != value:
                        self.current = value
                        updated = True

                else:
                    _LOGGER.debug("Unhandled measurand: %s=%s", measurand, value)

        if updated:
            _LOGGER.info(
                "Meter update: P=%sW E=%sWh V=%sV I=%sA",
                self.power,
                self.energy,
                self.voltage,
                self.current,
            )
            self.async_set_updated_data(True)
        else:
            _LOGGER.debug("MeterValues received but no values changed")

    # ─────────────────────────────
    # Growatt vendor data (DataTransfer)
    # ─────────────────────────────

    def process_vendor_data(self, message_id: str | None, data: dict) -> None:
        """Verwerk Growatt-specifieke DataTransfer payloads."""
        updated = False

        _LOGGER.debug(
            "Growatt DataTransfer received (message_id=%s): %s",
            message_id,
            data,
        )

        for key, value in data.items():
            try:
                if key == "maxCurrent":
                    if self.max_current != float(value):
                        self.max_current = float(value)
                        updated = True
                    else:
                        _LOGGER.debug("maxCurrent unchanged: %s", value)

                elif key == "maxPower":
                    if self.max_power != float(value):
                        self.max_power = float(value)
                        updated = True
                    else:
                        _LOGGER.debug("maxPower unchanged: %s", value)

                elif key == "mode":
                    if self.mode != str(value):
                        self.mode = str(value)
                        updated = True
                    else:
                        _LOGGER.debug("mode unchanged: %s", value)

                elif key == "lcd":
                    if self.lcd != str(value):
                        self.lcd = str(value)
                        updated = True
                    else:
                        _LOGGER.debug("lcd unchanged")

                else:
                    _LOGGER.debug(
                        "Unhandled Growatt DataTransfer field: %s=%s",
                        key,
                        value,
                    )

            except (TypeError, ValueError) as exc:
                _LOGGER.warning(
                    "Failed to process Growatt field %s=%s (%s)",
                    key,
                    value,
                    exc,
                )

        if updated:
            _LOGGER.info(
                "Growatt config update: mode=%s max_current=%s max_power=%s lcd=%s",
                self.mode,
                self.max_current,
                self.max_power,
                self.lcd,
            )
            self.async_set_updated_data(True)
        else:
            _LOGGER.debug("Growatt DataTransfer processed but no values changed")

    # ─────────────────────────────
    # Trigger support
    # ─────────────────────────────

    async def trigger_meter_update(self, charge_point) -> None:
        """Actieve polling via TriggerMessage."""
        _LOGGER.info("Triggering OCPP StatusNotification + MeterValues")

        try:
            await charge_point.trigger_message("StatusNotification")
            _LOGGER.debug("TriggerMessage(StatusNotification) sent")

            await charge_point.trigger_message("MeterValues")
            _LOGGER.debug("TriggerMessage(MeterValues) sent")

        except Exception as exc:
            _LOGGER.warning("TriggerMessage failed: %s", exc)
