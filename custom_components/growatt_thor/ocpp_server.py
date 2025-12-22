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
    """Growatt THOR OCPP 1.6 Charge Point."""

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
        _LOGGER.info("BootNotification payload: %s", payload)

        return call_result.BootNotification(
            current_time=self.coordinator.now(),
            interval=60,
            status=RegistrationStatus.accepted,
        )

    @on("Heartbeat")
    async def on_heartbeat(self, **payload):
        _LOGGER.debug("Heartbeat payload: %s", payload)

        return call_result.Heartbeat(
            current_time=self.coordinator.now()
        )

    # ─────────────────────────────
    # Authorization / transactions
    # ─────────────────────────────

    @on("Authorize")
    async def on_authorize(self, id_tag, **payload):
        _LOGGER.info("Authorize id_tag=%s payload=%s", id_tag, payload)

        return call_result.Authorize(
            id_tag_info={"status": AuthorizationStatus.accepted}
        )

    @on("StartTransaction")
    async def on_start_transaction(
        self,
        connector_id,
        id_tag,
        meter_start,
        timestamp,
        **payload,
    ):
        _LOGGER.info(
            "StartTransaction payload: connector=%s id_tag=%s meter_start=%s timestamp=%s extra=%s",
            connector_id,
            id_tag,
            meter_start,
            timestamp,
            payload,
        )

        transaction_id = self._transaction_id
        self._transaction_id += 1

        self.coordinator.start_transaction(transaction_id)

        return call_result.StartTransaction(
            transaction_id=transaction_id,
            id_tag_info={"status": AuthorizationStatus.accepted},
        )

    @on("StopTransaction")
    async def on_stop_transaction(
        self,
        transaction_id,
        meter_stop,
        timestamp,
        reason=None,
        **payload,
    ):
        _LOGGER.info(
            "StopTransaction payload: tx=%s meter_stop=%s reason=%s extra=%s",
            transaction_id,
            meter_stop,
            reason,
            payload,
        )

        self.coordinator.stop_transaction()

        return call_result.StopTransaction(
            id_tag_info={"status": AuthorizationStatus.accepted}
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
        timestamp=None,
        **payload,
    ):
        _LOGGER.info(
            "StatusNotification payload: connector=%s status=%s error=%s timestamp=%s extra=%s",
            connector_id,
            status,
            error_code,
            timestamp,
            payload,
        )

        self.coordinator.set_status(status)

        return call_result.StatusNotification()

    @on("MeterValues")
    async def on_meter_values(
        self,
        connector_id,
        meter_value,
        **payload,
    ):
        _LOGGER.debug(
            "MeterValues payload: connector=%s values=%s extra=%s",
            connector_id,
            meter_value,
            payload,
        )

        self.coordinator.process_meter_values(meter_value)

        return call_result.MeterValues()

    # ─────────────────────────────
    # Vendor specific
    # ─────────────────────────────

    @on("DataTransfer")
    async def on_data_transfer(
        self,
        vendor_id,
        message_id=None,
        data=None,
        **payload,
    ):
        _LOGGER.info(
            "DataTransfer payload: vendor=%s message_id=%s data=%s extra=%s",
            vendor_id,
            message_id,
            data,
            payload,
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

