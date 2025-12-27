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

        # 🔑 NA succesvolle boot: automatisch config ophalen
        self.hass.async_create_task(self.trigger_get_configuration())

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
    # Growatt vendor DataTransfer
    # ─────────────────────────────

    @on("DataTransfer")
    async def on_data_transfer(self, vendor_id, message_id=None, data=None, **kwargs):
        """Handle DataTransfer responses from charger."""
        
        _LOGGER.debug(
            "DataTransfer received: vendor=%s messageId=%s data=%s",
            vendor_id,
            message_id,
            data
        )
        
        try:
            # 🔹 Frozenrecord (end-of-session data)
            if isinstance(data, str) and message_id == "frozenrecord":
                parsed = {k: v[0] for k, v in parse_qs(data).items()}
                _LOGGER.info("Parsed frozenrecord: %s", parsed)
                self.coordinator.process_frozen_record(parsed)
            
            # 🔹 External meter values (grid connection)
            elif isinstance(data, str) and message_id == "get_external_meterval":
                _LOGGER.info("Received external meter values: %s", data)
                self.coordinator.process_external_meter(data)
                
        except Exception as exc:
            _LOGGER.exception("Failed to process DataTransfer: %s", exc)

        return call_result.DataTransferPayload(
            status=DataTransferStatus.accepted
        )

    # ─────────────────────────────
    # 🔑 Actieve triggers
    # ─────────────────────────────

    async def trigger_status(self):
        """Trigger StatusNotification update."""
        _LOGGER.info("Triggering StatusNotification")
        await self.call(
            call.TriggerMessagePayload(
                requested_message="StatusNotification",
                connector_id=1,
            )
        )

    async def trigger_external_meterval(self):
        """Trigger external meter values (grid connection data)."""
        _LOGGER.info("Triggering Growatt get_external_meterval")
        result = await self.call(
            call.DataTransferPayload(
                vendor_id="Growatt",
                message_id="get_external_meterval",
            )
        )
        # Response komt binnen via on_data_transfer callback
        _LOGGER.debug("External meterval trigger result: %s", result)

    async def trigger_get_configuration(self):
        """
        Haalt volledige Growatt configuratie op en zet deze door naar de coordinator
        """
        _LOGGER.info("Triggering GetConfiguration")

        result = await self.call(call.GetConfigurationPayload())

        config_keys = getattr(result, "configuration_key", [])
        unknown_keys = getattr(result, "unknown_key", [])

        _LOGGER.info(
            "Received Growatt configuration: %d keys (%d unknown)",
            len(config_keys),
            len(unknown_keys),
        )

        # 🔑 KOPPELING NAAR HA
        self.coordinator.process_configuration(config_keys)

        for item in config_keys:
            _LOGGER.debug(
                "Config key: %s = %s (readonly=%s)",
                item.get("key"),
                item.get("value"),
                item.get("readonly"),
            )


# ─────────────────────────────
# WebSocket server
# ─────────────────────────────

async def _on_connect(websocket, path, coordinator, hass):
    if not path.startswith(DEFAULT_PATH):
        await websocket.close()
        return

    cp_id = path.rstrip("/").split("/")[-1]
    _LOGGER.info("THOR connected: %s", cp_id)

    cp = GrowattChargePoint(cp_id, websocket, coordinator, hass)

    try:
        await cp.start()
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

