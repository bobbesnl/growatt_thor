import logging
from websockets.server import serve

from ocpp.v16 import ChargePoint as OcppChargePoint
from ocpp.v16.enums import RegistrationStatus, AuthorizationStatus
from ocpp.routing import on
from ocpp.v16 import call_result

from .const import OCPP_SUBPROTOCOL, DEFAULT_PATH

_LOGGER = logging.getLogger(__name__)


class GrowattChargePoint(OcppChargePoint):
    def __init__(self, cp_id, websocket, coordinator):
        super().__init__(cp_id, websocket)
        self.coordinator = coordinator
        self.coordinator.set_charge_point(cp_id)
        self._transaction_id = None

    # 🔹 Boot
    @on("BootNotification")
    async def on_boot_notification(self, **kwargs):
        _LOGGER.info(
            "BootNotification from %s (vendor=%s model=%s fw=%s serial=%s)",
            self.id,
            kwargs.get("chargePointVendor"),
            kwargs.get("chargePointModel"),
            kwargs.get("firmwareVersion"),
            kwargs.get("serialNumber"),
        )

        return call_result.BootNotificationPayload(
            currentTime=self.coordinator.now(),
            interval=60,
            status=RegistrationStatus.accepted,
        )

    # 🔹 Heartbeat
    @on("Heartbeat")
    async def on_heartbeat(self, **kwargs):
        _LOGGER.debug("Heartbeat from %s", self.id)
        return call_result.HeartbeatPayload(
            currentTime=self.coordinator.now()
        )

    # 🔹 Status
    @on("StatusNotification")
    async def on_status_notification(
        self, connectorId, status, errorCode, timestamp=None, **kwargs
    ):
        _LOGGER.info(
            "StatusNotification %s: connector=%s status=%s error=%s",
            self.id,
            connectorId,
            status,
            errorCode,
        )
        self.coordinator.set_status(status)
        return call_result.StatusNotificationPayload()

    # 🔹 Authorize (THOR stuurt dit vaak automatisch)
    @on("Authorize")
    async def on_authorize(self, idTag, **kwargs):
        _LOGGER.info("Authorize request from %s idTag=%s", self.id, idTag)

        return call_result.AuthorizePayload(
            idTagInfo={
                "status": AuthorizationStatus.accepted
            }
        )

    # 🔹 StartTransaction
    @on("StartTransaction")
    async def on_start_transaction(
        self, connectorId, idTag, meterStart, timestamp, **kwargs
    ):
        self._transaction_id = 1  # lokaal ID, HA-side
        _LOGGER.info(
            "StartTransaction %s: connector=%s idTag=%s meterStart=%s",
            self.id,
            connectorId,
            idTag,
            meterStart,
        )

        return call_result.StartTransactionPayload(
            transactionId=self._transaction_id,
            idTagInfo={
                "status": AuthorizationStatus.accepted
            },
        )

    # 🔹 StopTransaction
    @on("StopTransaction")
    async def on_stop_transaction(
        self, transactionId, meterStop, timestamp, reason=None, **kwargs
    ):
        _LOGGER.info(
            "StopTransaction %s: transactionId=%s meterStop=%s reason=%s",
            self.id,
            transactionId,
            meterStop,
            reason,
        )
        self._transaction_id = None

        return call_result.StopTransactionPayload()

    # 🔹 MeterValues (hier komen je HA-sensors vandaan)
    @on("MeterValues")
    async def on_meter_values(
        self, connectorId, meterValue, transactionId=None, **kwargs
    ):
        self.coordinator.process_meter_values(meterValue)
        return call_result.MeterValuesPayload()

    # 🔹 Growatt vendor-specific (veilig accepteren)
    @on("DataTransfer")
    async def on_data_transfer(
        self, vendorId, messageId=None, data=None, **kwargs
    ):
        _LOGGER.debug(
            "DataTransfer from %s vendor=%s messageId=%s data=%s",
            self.id,
            vendorId,
            messageId,
            data,
        )

        # We accepteren dit, maar doen er (nog) niets mee
        return call_result.DataTransferPayload(
            status="Accepted"
        )


async def _on_connect(websocket, path, coordinator):
    if not path.startswith(DEFAULT_PATH):
        _LOGGER.warning("Rejected connection on unexpected path: %s", path)
        await websocket.close()
        return

    parts = path.rstrip("/").split("/")
    cp_id = parts[-1] if len(parts) > 2 else "growatt_thor"

    _LOGGER.info("THOR connected with ChargePointId '%s'", cp_id)

    charge_point = GrowattChargePoint(cp_id, websocket, coordinator)

    try:
        await charge_point.start()
    except Exception as err:
        _LOGGER.exception("OCPP session error for %s: %s", cp_id, err)


async def start_ocpp_server(host, port, coordinator):
    _LOGGER.info("Starting OCPP server on %s:%s%s", host, port, DEFAULT_PATH)

    return await serve(
        lambda ws, path: _on_connect(ws, path, coordinator),
        host,
        port,
        subprotocols=[OCPP_SUBPROTOCOL],
    )

