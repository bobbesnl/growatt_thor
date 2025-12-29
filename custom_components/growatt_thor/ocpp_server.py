import logging
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

            # 🔑 NA succesvolle boot: automatisch config + grid data ophalen
            self.hass.async_create_task(self.trigger_get_configuration())
            self.hass.async_create_task(self.trigger_external_meterval())

            return call_result.BootNotificationPayload(
                current_time=self.coordinator.now(),
                interval=60,
                status=RegistrationStatus.accepted,
            )

        except Exception as exc:
            _LOGGER.error(
                "Error in BootNotification handler: %s",
                exc,
                exc_info=True
            )
            # Return safe fallback - accept anyway (otherwise no connection)
            return call_result.BootNotificationPayload(
                current_time=self.coordinator.now(),
                interval=60,
                status=RegistrationStatus.accepted,
            )

    @on("Heartbeat")
    async def on_heartbeat(self, **payload):
        """Handle heartbeat with TIER 2 error recovery."""
        try:
            return call_result.HeartbeatPayload(
                current_time=self.coordinator.now()
            )
        except Exception as exc:
            _LOGGER.error(
                "Error in Heartbeat handler: %s",
                exc,
                exc_info=True
            )
            # Return safe fallback
            return call_result.HeartbeatPayload(
                current_time=self.coordinator.now()
            )

    # ─────────────────────────────
    # Transactions
    # ─────────────────────────────

    @on("Authorize")
    async def on_authorize(self, id_tag, **kwargs):
        """Handle authorization with TIER 2 error recovery."""
        try:
            return call_result.AuthorizePayload(
                id_tag_info={"status": AuthorizationStatus.accepted}
            )
        except Exception as exc:
            _LOGGER.error(
                "Error in Authorize handler for idTag=%s: %s",
                id_tag,
                exc,
                exc_info=True
            )
            # Return safe fallback (reject to be safe)
            return call_result.AuthorizePayload(
                id_tag_info={"status": AuthorizationStatus.invalid}
            )

    @on("StartTransaction")
    async def on_start_transaction(self, connector_id, id_tag, meter_start, **kwargs):
        """Handle transaction start with TIER 2 error recovery."""
        try:
            transaction_id = self._transaction_id
            self._transaction_id += 1

            self.coordinator.start_transaction(transaction_id, id_tag)

            return call_result.StartTransactionPayload(
                transaction_id=transaction_id,
                id_tag_info={"status": AuthorizationStatus.accepted},
            )

        except Exception as exc:
            _LOGGER.error(
                "Error in StartTransaction handler (connector=%s, idTag=%s): %s",
                connector_id,
                id_tag,
                exc,
                exc_info=True
            )
            # Return safe fallback (reject to prevent zombie transactions)
            return call_result.StartTransactionPayload(
                transaction_id=0,
                id_tag_info={"status": AuthorizationStatus.invalid},
            )

    @on("StopTransaction")
    async def on_stop_transaction(self, transaction_id, meter_stop, reason=None, **kwargs):
        """Handle transaction stop with TIER 2 error recovery."""
        try:
            self.coordinator.stop_transaction(reason)
            return call_result.StopTransactionPayload(
                id_tag_info={"status": AuthorizationStatus.accepted}
            )
        except Exception as exc:
            _LOGGER.error(
                "Error in StopTransaction handler (transaction_id=%s): %s",
                transaction_id,
                exc,
                exc_info=True
            )
            # Return safe fallback (accept stop anyway - always allow stopping)
            return call_result.StopTransactionPayload(
                id_tag_info={"status": AuthorizationStatus.accepted}
            )

    # ─────────────────────────────
    # Status & Metering
    # ─────────────────────────────

    @on("StatusNotification")
    async def on_status_notification(self, connector_id, status, error_code=None, **kwargs):
        """Handle status notification with TIER 2 error recovery."""
        try:
            self.coordinator.set_status(status)
            return call_result.StatusNotificationPayload()
        except Exception as exc:
            _LOGGER.error(
                "Error in StatusNotification handler (status=%s): %s",
                status,
                exc,
                exc_info=True
            )
            # Return safe fallback (accept anyway - status updates are safe)
            return call_result.StatusNotificationPayload()

    @on("MeterValues")
    async def on_meter_values(self, connector_id, meter_value, **kwargs):
        """Handle meter values with TIER 2 error recovery."""
        try:
            self.coordinator.process_meter_values(meter_value)
            return call_result.MeterValuesPayload()
        except Exception as exc:
            _LOGGER.error(
                "Error in MeterValues handler: %s",
                exc,
                exc_info=True
            )
            # Return safe fallback (accept anyway - meter values are safe)
            return call_result.MeterValuesPayload()

    # ─────────────────────────────
    # Growatt vendor DataTransfer
    # ─────────────────────────────

    @on("DataTransfer")
    async def on_data_transfer(self, vendor_id, message_id=None, data=None, **kwargs):
        """Handle DataTransfer responses with TIER 2 error recovery."""

        try:
            _LOGGER.debug(
                "DataTransfer received: vendor=%s messageId=%s data=%s",
                vendor_id,
                message_id,
                data
            )

            # 🔹 Frozenrecord (end-of-session data)
            if isinstance(data, str) and message_id == "frozenrecord":
                parsed = {k: v[0] for k, v in parse_qs(data).items()}
                _LOGGER.info("Parsed frozenrecord: %s", parsed)
                self.coordinator.process_frozen_record(parsed)

            # 🔹 External meter values (grid connection) - RESPONSE komt hier NIET binnen!
            # Deze komt terug via de CALL response in trigger_external_meterval()

        except Exception as exc:
            _LOGGER.error(
                "Error in DataTransfer handler (vendor=%s, messageId=%s): %s",
                vendor_id,
                message_id,
                exc,
                exc_info=True
            )
            # Don't crash - just log and continue

        # Always return accepted (TIER 2: graceful degradation)
        return call_result.DataTransferPayload(
            status=DataTransferStatus.accepted
        )

    # ─────────────────────────────
    # 🔑 Actieve triggers
    # ─────────────────────────────

    async def trigger_status(self):
        """Trigger StatusNotification with TIER 2 error recovery."""
        try:
            _LOGGER.info("Triggering StatusNotification")
            await self.call(
                call.TriggerMessagePayload(
                    requested_message="StatusNotification",
                    connector_id=1,
                )
            )
        except Exception as exc:
            _LOGGER.warning(
                "Failed to trigger StatusNotification: %s",
                exc
            )
            # Don't crash - just log and continue

    async def trigger_external_meterval(self):
        """Trigger external meter values with TIER 2 error recovery."""
        _LOGGER.info("Triggering Growatt get_external_meterval")

        try:
            result = await self.call(
                call.DataTransferPayload(
                    vendor_id="Growatt",
                    message_id="get_external_meterval",
                )
            )

            # Response komt DIRECT terug als result.data (niet via on_data_transfer!)
            if hasattr(result, 'data') and isinstance(result.data, str):
                _LOGGER.info("Received external meter values: %s", result.data)
                self.coordinator.process_external_meter(result.data)
            else:
                _LOGGER.debug("External meterval result: %s", result)

        except Exception as exc:
            _LOGGER.warning(
                "Failed to trigger external meter values: %s",
                exc
            )
            # Don't crash - coordinator has error handling

    async def trigger_get_configuration(self):
        """Trigger configuration retrieval with TIER 2 error recovery."""
        try:
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

        except Exception as exc:
            _LOGGER.warning(
                "Failed to trigger GetConfiguration: %s",
                exc
            )
            # Don't crash - just log and continue

    # ─────────────────────────────
    # 🔧 ChangeConfiguration
    # ─────────────────────────────

    async def change_configuration(self, key: str, value: str):
        """Change a configuration key on the charger.
        
        Args:
            key: Configuration key (e.g. "G_MaxCurrent")
            value: New value as string (e.g. "16.00")
            
        Returns:
            ConfigurationStatus enum value (Accepted, Rejected, RebootRequired, NotSupported)
        """
        try:
            _LOGGER.info("ChangeConfiguration: %s = %s", key, value)

            result = await self.call(
                call.ChangeConfigurationPayload(
                    key=key,
                    value=value
                )
            )

            status = getattr(result, "status", ConfigurationStatus.rejected)
            _LOGGER.info("ChangeConfiguration result: %s", status)

            # Refresh configuration na succesvol wijzigen
            if status == ConfigurationStatus.accepted:
                self.hass.async_create_task(self.trigger_get_configuration())

            return status

        except Exception as exc:
            _LOGGER.error(
                "Failed to change configuration %s=%s: %s",
                key,
                value,
                exc,
                exc_info=True
            )
            return ConfigurationStatus.rejected


# ─────────────────────────────
# WebSocket server
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

        try:
            await cp.start()
        finally:
            hass.data.get(DOMAIN, {}).pop("charge_point", None)
            coordinator.set_status("Unavailable")

    except Exception as exc:
        _LOGGER.error(
            "Error in connection handler: %s",
            exc,
            exc_info=True
        )
        # Try to close websocket gracefully
        try:
            await websocket.close()
        except Exception:
            pass


async def start_ocpp_server(host, port, coordinator, hass):
    """Start OCPP server with TIER 2 error recovery."""
    try:
        _LOGGER.info("Starting OCPP server on %s:%s", host, port)
        return await serve(
            lambda ws, path: _on_connect(ws, path, coordinator, hass),
            host,
            port,
            subprotocols=[OCPP_SUBPROTOCOL],
        )
    except Exception as exc:
        _LOGGER.error(
            "Failed to start OCPP server: %s",
            exc,
            exc_info=True
        )
        raise  # Re-raise - integration can't work without server

