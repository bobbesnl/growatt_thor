import logging
import asyncio
import websockets.exceptions
from urllib.parse import parse_qs
from websockets.server import serve

from ocpp.v16 import ChargePoint as OcppChargePoint
from ocpp.v16 import call_result, call
from ocpp.v16.enums import (
    RegistrationStatus,
    AuthorizationStatus,
    DataTransferStatus,
    ConfigurationStatus,
)

from ocpp.routing import on

from .const import OCPP_SUBPROTOCOL, DEFAULT_PATH, DOMAIN

_LOGGER = logging.getLogger(__name__)


class GrowattChargePoint(OcppChargePoint):
    """
    Growatt THOR OCPP 1.6 Charge Point with TIER 2 error recovery
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
        """Handle boot notification with TIER 2 error recovery."""
        try:
            _LOGGER.info("BootNotification payload: %s", payload)

            # 🔑 BootNotification: ook config refreshen (voor de zekerheid)
            self.hass.async_create_task(self._post_connect_init())

            return call_result.BootNotificationPayload(
                current_time=self.coordinator.now(),
                interval=60,
                status=RegistrationStatus.accepted,
            )

        except Exception as exc:
            _LOGGER.error("Error in BootNotification handler: %s", exc, exc_info=True)
            return call_result.BootNotificationPayload(
                current_time=self.coordinator.now(),
                interval=60,
                status=RegistrationStatus.accepted,
            )

    @on("Heartbeat")
    async def on_heartbeat(self, **payload):
        """Handle heartbeat + trigger config op EERSTE heartbeat."""
        try:
            # 🔑 EERSTE HEARTBEAT: config ophalen!
            if not hasattr(self, '_heartbeat_done'):
                self._heartbeat_done = True
                _LOGGER.info("⭐ First Heartbeat → Auto fetching configuration...")
                self.hass.async_create_task(self._post_connect_init())

            return call_result.HeartbeatPayload(
                current_time=self.coordinator.now()
            )
        except Exception as exc:
            _LOGGER.error("Error in Heartbeat handler: %s", exc)
            return call_result.HeartbeatPayload(current_time=self.coordinator.now())

    # ─────────────────────────────
    # Helper: Post-connect init
    # ─────────────────────────────

    async def _post_connect_init(self):
        """Initialize after first heartbeat or boot notification."""
        try:
            await asyncio.sleep(1)  # Stabiliteit

            _LOGGER.info("🔄 Auto GetConfiguration after connect")
            await self.trigger_get_configuration()

            # 🔑 SMART: External meter ALLEEN bij load balancing AAN
            if self.coordinator.external_limit_power_enable:
                _LOGGER.info("🔄 Auto external meterval (load balancing ON)")
                await self.trigger_external_meterval()
            else:
                _LOGGER.debug("⏸️ Skip external meterval (load balancing OFF)")

        except Exception as exc:
            _LOGGER.warning("Post-connect init failed: %s", exc)

    # ─────────────────────────────
    # Transactions
    # ─────────────────────────────

    @on("Authorize")
    async def on_authorize(self, id_tag, **kwargs):
        try:
            return call_result.AuthorizePayload(
                id_tag_info={"status": AuthorizationStatus.accepted}
            )
        except Exception as exc:
            _LOGGER.error("Error in Authorize handler for idTag=%s: %s", id_tag, exc, exc_info=True)
            return call_result.AuthorizePayload(
                id_tag_info={"status": AuthorizationStatus.invalid}
            )

    @on("StartTransaction")
    async def on_start_transaction(self, connector_id, id_tag, meter_start, **kwargs):
        try:
            transaction_id = self._transaction_id
            self._transaction_id += 1

            self.coordinator.start_transaction(transaction_id, id_tag)

            return call_result.StartTransactionPayload(
                transaction_id=transaction_id,
                id_tag_info={"status": AuthorizationStatus.accepted},
            )
        except Exception as exc:
            _LOGGER.error("Error in StartTransaction handler (connector=%s, idTag=%s): %s", connector_id, id_tag, exc, exc_info=True)
            return call_result.StartTransactionPayload(
                transaction_id=0,
                id_tag_info={"status": AuthorizationStatus.invalid},
            )

    @on("StopTransaction")
    async def on_stop_transaction(self, transaction_id, meter_stop, reason=None, **kwargs):
        try:
            self.coordinator.stop_transaction(reason)
            return call_result.StopTransactionPayload(
                id_tag_info={"status": AuthorizationStatus.accepted}
            )
        except Exception as exc:
            _LOGGER.error("Error in StopTransaction handler (transaction_id=%s): %s", transaction_id, exc, exc_info=True)
            return call_result.StopTransactionPayload(
                id_tag_info={"status": AuthorizationStatus.accepted}
            )

    # ─────────────────────────────
    # Status & Metering
    # ─────────────────────────────

    @on("StatusNotification")
    async def on_status_notification(self, connector_id, status, error_code=None, **kwargs):
        try:
            self.coordinator.set_status(status)
            return call_result.StatusNotificationPayload()
        except Exception as exc:
            _LOGGER.error("Error in StatusNotification handler (status=%s): %s", status, exc, exc_info=True)
            return call_result.StatusNotificationPayload()

    @on("MeterValues")
    async def on_meter_values(self, connector_id, meter_value, **kwargs):
        try:
            self.coordinator.process_meter_values(meter_value)
            return call_result.MeterValuesPayload()
        except Exception as exc:
            _LOGGER.error("Error in MeterValues handler: %s", exc, exc_info=True)
            return call_result.MeterValuesPayload()

    # ─────────────────────────────
    # Growatt vendor DataTransfer
    # ─────────────────────────────

    @on("DataTransfer")
    async def on_data_transfer(self, vendor_id, message_id=None, data=None, **kwargs):
        try:
            _LOGGER.debug("DataTransfer received: vendor=%s messageId=%s data=%s", vendor_id, message_id, data)

            if isinstance(data, str) and message_id == "frozenrecord":
                parsed = {k: v[0] for k, v in parse_qs(data).items()}
                _LOGGER.info("Parsed frozenrecord: %s", parsed)
                self.coordinator.process_frozen_record(parsed)

        except Exception as exc:
            _LOGGER.error("Error in DataTransfer handler (vendor=%s, messageId=%s): %s", vendor_id, message_id, exc, exc_info=True)

        return call_result.DataTransferPayload(status=DataTransferStatus.accepted)

    # ─────────────────────────────
    # 🔑 Actieve triggers
    # ─────────────────────────────

    async def trigger_status(self):
        try:
            _LOGGER.info("Triggering StatusNotification")
            await self.call(call.TriggerMessagePayload(requested_message="StatusNotification", connector_id=1))
        except Exception as exc:
            _LOGGER.warning("Failed to trigger StatusNotification: %s", exc)

    async def trigger_external_meterval(self):
        _LOGGER.info("Triggering Growatt get_external_meterval")
        try:
            result = await self.call(call.DataTransferPayload(vendor_id="Growatt", message_id="get_external_meterval"))

            if hasattr(result, 'data') and isinstance(result.data, str):
                _LOGGER.info("Received external meter values: %s", result.data)
                self.coordinator.process_external_meter(result.data)
            else:
                _LOGGER.debug("External meterval result: %s", result)

        except Exception as exc:
            _LOGGER.warning("Failed to trigger external meter values: %s", exc)

    async def trigger_get_configuration(self):
        try:
            _LOGGER.info("Triggering GetConfiguration")

            result = await asyncio.wait_for(
                self.call(call.GetConfigurationPayload()),
                timeout=30.0
            )

            config_keys = getattr(result, "configuration_key", [])
            unknown_keys = getattr(result, "unknown_key", [])

            _LOGGER.info("Received Growatt configuration: %d keys (%d unknown)", len(config_keys), len(unknown_keys))
            self.coordinator.process_configuration(config_keys)

            for item in config_keys:
                _LOGGER.debug("Config key: %s = %s (readonly=%s)", 
                            item.get("key"), item.get("value"), item.get("readonly"))

        except asyncio.TimeoutError:
            _LOGGER.warning("GetConfiguration timeout - Thor likely rebooting, will retry on reconnect")
        except Exception as exc:
            _LOGGER.warning("Failed to trigger GetConfiguration: %s", exc)

    # ─────────────────────────────
    # 🔧 ChangeConfiguration
    # ─────────────────────────────

    async def change_configuration(self, key: str, value: str):
        try:
            _LOGGER.info("ChangeConfiguration: %s = %s", key, value)

            result = await self.call(call.ChangeConfigurationPayload(key=key, value=value))

            status = getattr(result, "status", ConfigurationStatus.rejected)
            _LOGGER.info("ChangeConfiguration result: %s", status)

            # 🚫 NO GetConfiguration trigger - Thor doet dit automatisch na reboot!
            _LOGGER.debug("⏳ Config change accepted. Thor will send GetConfiguration on reconnect.")

            return status

        except Exception as exc:
            _LOGGER.error("Failed to change configuration %s=%s: %s", key, value, exc, exc_info=True)
            return ConfigurationStatus.rejected

# ─────────────────────────────
# WebSocket server (SCHOON - GEEN vroege triggers)
# ─────────────────────────────

async def _on_connect(websocket, path, coordinator, hass):
    """Handle new connection with TIER 2 error recovery."""
    try:
        if not path.startswith(DEFAULT_PATH):
            await websocket.close()
            return

        cp_id = path.rstrip("/").split("/")[-1]
        _LOGGER.info("THOR connected: %s", cp_id)

        cp = GrowattChargePoint(cp_id, websocket, coordinator, hass)

        # ✅ GEEN vroege triggers meer - wachten op Heartbeat!

        try:
            await cp.start()
        except websockets.exceptions.ConnectionClosedError:
            _LOGGER.debug("Connection closed normally during startup - THOR disconnected")
        except Exception as exc:
            _LOGGER.error("Error in connection handler: %s", exc, exc_info=True)
        finally:
            hass.data.get(DOMAIN, {}).pop("charge_point", None)
            coordinator.set_status("Unavailable")

    except Exception as exc:
        _LOGGER.error("Error in connection handler: %s", exc, exc_info=True)
        try:
            await websocket.close()
        except Exception:
            pass


async def start_ocpp_server(host, port, coordinator, hass):
    try:
        _LOGGER.info("Starting OCPP server on %s:%s", host, port)
        return await serve(
            lambda ws, path: _on_connect(ws, path, coordinator, hass),
            host,
            port,
            subprotocols=[OCPP_SUBPROTOCOL],
        )
    except Exception as exc:
        _LOGGER.error("Failed to start OCPP server: %s", exc, exc_info=True)
        raise

