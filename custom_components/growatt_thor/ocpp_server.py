import logging
from websockets.server import serve

from ocpp.v16 import ChargePoint as OcppChargePoint
from ocpp.v16 import call_result
from ocpp.v16.enums import (
    RegistrationStatus,
    AuthorizationStatus,
    DataTransferStatus,
)
from ocpp.routing import on

from .const import OCPP_SUBPROTOCOL, DEFAULT_PATH

_LOGGER = logging.getLogger(__name__)


class GrowattChargePoint(OcppChargePoint):
    """Growatt THOR OCPP 1.6 Charge Point (stub implementation)."""

    def __init__(self, cp_id, websocket, coordinator):
        super().__init__(cp_id, websocket)
        self.coordinator = coordinator
        self.coordinator.set_charge_point(cp_id)

        self._transaction_id = 1

    # ─────────────────────────────
    # Boot / keepalive
    # ─────────────────────────────

    @on("BootNotification")
    async def on_boot_notification(self, **payload):
        _LOGGER.info("BootNotification from %s: %s", self.id, payload)

        return call_result.BootNotification(
            currentTime=self.coordinator.now(),
            interval=60,
            status=RegistrationStatus.accepted,
        )

    @on("Heartbeat")
    async def on_heartbeat(self):
        _LOGGER.debug("Heartbeat from %s", self.id)

        return call_result.Heartbeat(
            currentTime=self.coordinator.now()
        )

    # ─────────────────────────────
    # Authorization / transactions
    # ─────────────────────────────

    @on("Authorize")
    async def on_authorize(self, id_tag, **kwargs):
        _LOGGER.info("Authorize id_tag=%s", id_tag)

        return call_result.Authorize(
            idTagInfo={"status": AuthorizationStatus.accepted}
        )

    @on("StartTransaction")
    async def on_start_transaction(
        self,
        connector_id,
        id_tag,
        meter_start,
        timestamp,
        **kwargs,
    ):
        _LOGGER.info(
            "StartTransaction connector=%s id_tag=%s meter_start=%s",
            connector_id,
            id_tag,
            meter_start,
        )

        transaction_id = self._transaction_id
        self._transaction_id += 1

        self.coordinator.status = "Charging"
        self.coordinator.transaction_id = transaction_id

        return call_result.StartTransaction(
            transactionId=transaction_id,
            idTagInfo={"status": AuthorizationStatus.accepted},
        )

    @on("StopTransaction")
    async def on_stop_transaction(
        self,
        transaction_id,
        meter_stop,
        timestamp,
        reason=None,
        **kwargs,
    ):
        _LOGGER.info(
            "StopTransaction tx=%s meter_stop=%s reason=%s",
            transaction_id,
            meter_stop,
            reason,
        )

        self.coordinator.status = "Idle"
        self.coordinator.transaction_id = None

        return call_result.StopTransaction(
            idTagInfo={"status": AuthorizationStatus.accepted}
        )

    # ─────────────────────────────
    # Status & metering
    # ─────────────────────────────

    @on("StatusNotification")
    async def on_status_notification(
        self,
        connector_id,
        status,
        error_code,
        timestamp,
        **kwargs,
    ):
        _LOGGER.info(
            "StatusNotification connector=%s status=%s error=%s",
            connector_id,
            status,
            error_code,
        )

        self.coordinator.set_status(status)

        return call_result.StatusNotification()

    @on("MeterValues")
    async def on_meter_values(
        self,
        connector_id,
        meter_value,
        **kwargs,
    ):
        _LOGGER.debug("MeterValues from connector %s", connector_id)

        self.coordinator.process_meter_values(meter_value)

        return call_result.MeterValues()

    # ─────────────────────────────
    # Vendor specific (Growatt)
    # ─────────────────────────────

    @on("DataTransfer")
    async def on_data_transfer(
        self,
        vendor_id,
        message_id=None,
        data=None,
        **kwargs,
    ):
        _LOGGER.info(
            "DataTransfer vendor=%s message_id=%s data=%s",
            vendor_id,
            message_id,
            data,
        )

        return call_result.DataTransfer(
            status=DataTransferStatus.accepted
        )


# ─────────────────────────────
# WebSocket server
# ─────────────────────────────

async def _on_connect(websocket, path, coordinator):
    if not path.startswith(DEFAULT_PATH):
        _LOGGER.warning("Rejected connection on path %s", path)
        await websocket.close()
        return

    parts = path.rstrip("/").split("/")
    cp_id = parts[-1] if len(parts) > 3 else "UNKNOWN"

    _LOGGER.info("THOR connected with ChargePointId %s", cp_id)

    charge_point = GrowattChargePoint(cp_id, websocket, coordinator)

    try:
        await charge_point.start()
    except Exception:
        _LOGGER.exception("OCPP session error for %s", cp_id)


async def start_ocpp_server(host, port, coordinator):
    _LOGGER.info("Starting OCPP server on %s:%s", host, port)

    return await serve(
        lambda ws, path: _on_connect(ws, path, coordinator),
        host,
        port,
        subprotocols=[OCPP_SUBPROTOCOL],
    )

