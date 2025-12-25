import logging
from urllib.parse import parse_qs
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
    """
    Growatt THOR OCPP 1.6 Charge Point
    """

    def __init__(self, cp_id, websocket, coordinator, hass):
        super().__init__(cp_id, websocket)

        self.coordinator = coordinator
        self.hass = hass
        self._transaction_id = 1

        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN]["charge_point"] = self

        self.coordinator.set_charge_point(cp_id)
        _LOGGER.info("GrowattChargePoint initialised for %s", cp_id)

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
    # Transactions
    # ─────────────────────────────

    @on("Authorize")
    async def on_authorize(self, id_tag, **kwargs):
        return call_result.AuthorizePayload(
            id_tag_info={"status": AuthorizationStatus.accepted}
        )

    @on("StartTransaction")
    async def on_start_transaction(self, connector_id, id_tag, meter_start, **kwargs):
        transaction_id = self._transaction_id
        self._transaction_id += 1

        self.coordinator.start_transaction(transaction_id, id_tag)

        return call_result.StartTransactionPayload(
            transaction_id=transaction_id,
            id_tag_info={"status": AuthorizationStatus.accepted},
        )

    @on("StopTransaction")
    async def on_stop_transaction(self, transaction_id, meter_stop, reason=None, **kwargs):
        self.coordinator.stop_transaction(reason)
        return call_result.StopTransactionPayload(
            id_tag_info={"status": AuthorizationStatus.accepted}
        )

    # ─────────────────────────────
    # Status & Metering
    # ─────────────────────────────

    @on("StatusNotification")
    async def on_status_notification(self, connector_id, status, error_code=None, **kwargs):
        self.coordinator.set_status(status)
        return call_result.StatusNotificationPayload()

    @on("MeterValues")
    async def on_meter_values(self, connector_id, meter_value, **kwargs):
        self.coordinator.process_meter_values(meter_value)
        return call_result.MeterValuesPayload()

    # ─────────────────────────────
    # GetConfiguration (🔑 instellingen!)
    # ─────────────────────────────

    @on("GetConfiguration")
    async def on_get_configuration(self, **payload):
        """
        Antwoord van de lader met config-waarden
        """
        configuration = payload.get("configurationKey", [])
        _LOGGER.info("GetConfiguration response: %s", configuration)

        self.coordinator.process_configuration(configuration)

        return call_result.GetConfigurationPayload()

    # ─────────────────────────────
    # Growatt vendor DataTransfer
    # ─────────────────────────────

    @on("DataTransfer")
    async def on_data_transfer(self, vendor_id, message_id=None, data=None, **kwargs):
        if isinstance(data, str) and message_id == "frozenrecord":
            parsed = {k: v[0] for k, v in parse_qs(data).items()}
            self.coordinator.process_frozen_record(parsed)

        return call_result.DataTransferPayload(
            status=DataTransferStatus.accepted
        )

    # ─────────────────────────────
    # 🔑 Actieve triggers
    # ─────────────────────────────

    async def trigger_status(self):
        await self.call(
            call.TriggerMessagePayload(
                requested_message="StatusNotification",
                connector_id=1,
            )
        )

    async def trigger_external_meterval(self):
        await self.call(
            call.DataTransferPayload(
                vendor_id="Growatt",
                message_id="get_external_meterval",
            )
        )

    async def trigger_get_configuration(self):
        """
        Vraag alle Growatt-config op
        """
        _LOGGER.info("Triggering GetConfiguration (Growatt)")
        await self.call(
            call.GetConfigurationPayload()
        )


# ─────────────────────────────
# WebSocket server
# ─────────────────────────────

async def _on_connect(websocket, path, coordinator, hass):
    if not path.startswith(DEFAULT_PATH):
        await websocket.close()
        return

    cp_id = path.rstrip("/").split("/")[-1]
    cp = GrowattChargePoint(cp_id, websocket, coordinator, hass)

    try:
        await cp.start()
    finally:
        hass.data.get(DOMAIN, {}).pop("charge_point", None)
        coordinator.set_status("Unavailable")


async def start_ocpp_server(host, port, coordinator, hass):
    return await serve(
        lambda ws, path: _on_connect(ws, path, coordinator, hass),
        host,
        port,
        subprotocols=[OCPP_SUBPROTOCOL],
    )

