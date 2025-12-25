import logging
from websockets.server import serve

from ocpp.v16 import ChargePoint as OcppChargePoint
from ocpp.v16 import call_result, call
from ocpp.v16.enums import (
    RegistrationStatus,
    AuthorizationStatus,
    DataTransferStatus,
)
from ocpp.routing import on

from .const import OCPP_SUBPROTOCOL, DEFAULT_PATH, DOMAIN

_LOGGER = logging.getLogger(__name__)


class GrowattChargePoint(OcppChargePoint):
    """Growatt THOR OCPP 1.6 Charge Point (HA-safe, Growatt-aware)."""

    def __init__(self, cp_id, websocket, coordinator, hass):
        super().__init__(cp_id, websocket)

        self.coordinator = coordinator
        self.hass = hass
        self._transaction_id = 1

        # expose CP to Home Assistant (services / polling)
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN]["charge_point"] = self

        self.coordinator.set_charge_point(cp_id)

    # ─────────────────────────────
    # Boot / keepalive
    # ─────────────────────────────

    @on("BootNotification")
    async def on_boot_notification(self, **payload):
        _LOGGER.info("BootNotification payload: %s", payload)

        return call_result.BootNotificationPayload(
            current_time=self.coordinator.now(),
            interval=60,
            status=RegistrationStatus.accepted,
        )

    @on("Heartbeat")
    async def on_heartbeat(self, **payload):
        return call_result.HeartbeatPayload(
            current_time=self.coordinator.now()
        )

    # ─────────────────────────────
    # Authorization / transactions
    # ─────────────────────────────

    @on("Authorize")
    async def on_authorize(self, id_tag, **kwargs):
        _LOGGER.info("Authorize id_tag=%s", id_tag)

        return call_result.AuthorizePayload(
            id_tag_info={"status": AuthorizationStatus.accepted}
        )

    @on("StartTransaction")
    async def on_start_transaction(
        self,
        connector_id,
        id_tag,
        meter_start,
        timestamp=None,
        **kwargs,
    ):
        _LOGGER.info(
            "StartTransaction: connector=%s id_tag=%s meter_start=%s",
            connector_id,
            id_tag,
            meter_start,
        )

        transaction_id = self._transaction_id
        self._transaction_id += 1

        self.coordinator.start_transaction(
            transaction_id=transaction_id,
            id_tag=id_tag,
        )

        return call_result.StartTransactionPayload(
            transaction_id=transaction_id,
            id_tag_info={"status": AuthorizationStatus.accepted},
        )

    @on("StopTransaction")
    async def on_stop_transaction(
        self,
        transaction_id,
        meter_stop,
        timestamp=None,
        reason=None,
        **kwargs,
    ):
        _LOGGER.info(
            "StopTransaction: tx=%s meter_stop=%s reason=%s",
            transaction_id,
            meter_stop,
            reason,
        )

        self.coordinator.stop_transaction(reason)

        return call_result.StopTransactionPayload(
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
        error_code=None,
        timestamp=None,
        **kwargs,
    ):
        _LOGGER.info(
            "StatusNotification: connector=%s status=%s error=%s",
            connector_id,
            status,
            error_code,
        )

        self.coordinator.set_status(status)

        return call_result.StatusNotificationPayload()

    @on("MeterValues")
    async def on_meter_values(
        self,
        connector_id,
        meter_value,
        **kwargs,
    ):
        _LOGGER.debug(
            "MeterValues: connector=%s values=%s",
            connector_id,
            meter_value,
        )

        self.coordinator.process_meter_values(meter_value)

        return call_result.MeterValuesPayload()

    # ─────────────────────────────
    # Vendor specific (Growatt!)
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
            "DataTransfer: vendor=%s message_id=%s data=%s",
            vendor_id,
            message_id,
            data,
        )

        if vendor_id == "Growatt" and isinstance(data, dict):
            self.coordinator.process_vendor_data(message_id, data)

        return call_result.DataTransferPayload(
            status=DataTransferStatus.accepted
        )

    # ─────────────────────────────
    # Active polling helpers
    # ─────────────────────────────

    async def trigger_message(self, message: str):
        """Generic TriggerMessage helper."""
        await self.call(
            call.TriggerMessagePayload(
                requested_message=message,
                connector_id=1,
            )
        )


# ─────────────────────────────
# WebSocket server
# ─────────────────────────────

async def _on_connect(websocket, path, coordinator, hass):
    if not path.startswith(DEFAULT_PATH):
        await websocket.close()
        return

    cp_id = path.rstrip("/").split("/")[-1]

    _LOGGER.info("THOR connected with ChargePointId %s", cp_id)

    charge_point = GrowattChargePoint(
        cp_id=cp_id,
        websocket=websocket,
        coordinator=coordinator,
        hass=hass,
    )

    try:
        await charge_point.start()
    except Exception:
        _LOGGER.exception("OCPP session error for %s", cp_id)
    finally:
        hass.data.get(DOMAIN, {}).pop("charge_point", None)
        coordinator.set_status("Unavailable")


async def start_ocpp_server(host, port, coordinator, hass):
    _LOGGER.info("Starting OCPP server on %s:%s", host, port)

    return await serve(
        lambda ws, path: _on_connect(ws, path, coordinator, hass),
        host,
        port,
        subprotocols=[OCPP_SUBPROTOCOL],
    )
