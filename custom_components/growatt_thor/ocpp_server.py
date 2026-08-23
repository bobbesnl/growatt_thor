import logging
import asyncio
import websockets.exceptions
from urllib.parse import parse_qs
from websockets.server import serve

from ocpp.v16 import ChargePoint as OcppChargePoint
from ocpp.v16 import call_result, call
from ocpp.messages import unpack
from ocpp.v16.enums import (
    RegistrationStatus,
    AuthorizationStatus,
    DataTransferStatus,
    ConfigurationStatus,
    RemoteStartStopStatus,
)

from ocpp.routing import on

from .configuration import (
    INFORMATIONAL_CONFIGURATION_KEYS,
    OPERATIONAL_CONFIGURATION_KEYS,
    normalize_unknown_configuration_keys,
    redact_configuration_value,
)
from .connection import (
    CONNECTION_WATCHDOG_INTERVAL_SECONDS,
    OCPP_HEARTBEAT_INTERVAL_SECONDS,
    OcppConnectionActivity,
)
from .const import OCPP_SUBPROTOCOL, DEFAULT_PATH, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _preload_ocpp_schemas():
    try:
        import importlib.metadata
        version = importlib.metadata.version("ocpp")
        _LOGGER.info("ocpp library version: %s", version)
    except Exception as exc:
        _LOGGER.warning("Could not determine ocpp library version: %s", exc)

    try:
        from ocpp.messages import get_validator, MessageType
        from ocpp.v16.enums import Action

        count = 0
        for action in Action:
            for message_type in [MessageType.Call, MessageType.CallResult]:
                try:
                    get_validator(message_type, action.value, "1.6")
                    count += 1
                except Exception:
                    pass

        _LOGGER.info("OCPP validator cache pre-loaded (%d validators)", count)

    except Exception as exc:
        _LOGGER.warning("OCPP schema pre-load failed (non-fatal): %s", exc)


class GrowattChargePoint(OcppChargePoint):
    """
    Growatt THOR OCPP 1.6 Charge Point with TIER 2 error recovery
    """

    def __init__(self, cp_id, websocket, coordinator, hass):
        super().__init__(cp_id, websocket)

        self.coordinator = coordinator
        self.hass = hass
        self._cp_id = cp_id
        self._websocket = websocket
        self._activity = OcppConnectionActivity(hass.loop.time())
        self._transaction_id = 1

        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN]["charge_point"] = self

        self.coordinator.set_charge_point(cp_id)
        _LOGGER.info("GrowattChargePoint initialised for %s", cp_id)

    def _is_current_connection(self):
        """Return whether this charge point owns the active connection slot."""
        return self.hass.data.get(DOMAIN, {}).get("charge_point") is self

    def _mark_activity(self, action):
        """Record an inbound message for the connection watchdog."""
        self._activity.mark(self.hass.loop.time())
        if self._is_current_connection():
            self.coordinator.mark_connection_activity(action)

    async def route_message(self, raw_msg):
        """Track every inbound OCPP frame before routing it."""
        action = "OCPPMessage"
        try:
            message = unpack(raw_msg)
            message_action = getattr(message, "action", None)
            if message_action is None:
                action = type(message).__name__
            elif hasattr(message_action, "value"):
                action = str(message_action.value)
            else:
                action = str(message_action)
        except Exception:
            action = "InvalidOCPPMessage"

        self._mark_activity(action)
        await super().route_message(raw_msg)

    async def async_watch_connection(self):
        """Close and invalidate a connection with no inbound OCPP activity."""
        while True:
            await asyncio.sleep(CONNECTION_WATCHDOG_INTERVAL_SECONDS)

            if not self._is_current_connection():
                return

            now_monotonic = self.hass.loop.time()
            if not self._activity.is_stale(now_monotonic):
                continue

            idle_seconds = self._activity.idle_seconds(now_monotonic)
            _LOGGER.warning(
                "No OCPP activity from %s for %.0f seconds; marking disconnected",
                self._cp_id,
                idle_seconds,
            )
            self.coordinator.set_disconnected()

            try:
                await asyncio.wait_for(
                    self._websocket.close(
                        code=1001,
                        reason="OCPP activity timeout",
                    ),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                _LOGGER.warning("Timed out closing stale OCPP connection: %s", self._cp_id)
                transport = getattr(self._websocket, "transport", None)
                if transport is not None:
                    transport.close()
            except Exception as exc:
                _LOGGER.debug(
                    "Failed to close stale OCPP connection %s: %s",
                    self._cp_id,
                    exc,
                )
            finally:
                domain_data = self.hass.data.get(DOMAIN, {})
                if domain_data.get("charge_point") is self:
                    domain_data.pop("charge_point", None)
            return

    # ─────────────────────────────
    # Boot / keepalive
    # ─────────────────────────────

    @on("BootNotification")
    async def on_boot_notification(self, **payload):
        try:
            _LOGGER.info("BootNotification payload: %s", payload)
            self.coordinator.record_boot_notification(payload)
            self.hass.async_create_task(self._post_connect_init())
            return call_result.BootNotification(
                current_time=self.coordinator.now(),
                interval=OCPP_HEARTBEAT_INTERVAL_SECONDS,
                status=RegistrationStatus.accepted,
            )
        except Exception as exc:
            _LOGGER.error("Error in BootNotification handler: %s", exc, exc_info=True)
            return call_result.BootNotification(
                current_time=self.coordinator.now(),
                interval=OCPP_HEARTBEAT_INTERVAL_SECONDS,
                status=RegistrationStatus.accepted,
            )

    @on("Heartbeat")
    async def on_heartbeat(self, **payload):
        try:
            if not hasattr(self, '_heartbeat_done'):
                self._heartbeat_done = True
                _LOGGER.info("⭐ First Heartbeat → Auto fetching configuration...")
                self.hass.async_create_task(self._post_connect_init())
            return call_result.Heartbeat(
                current_time=self.coordinator.now()
            )
        except Exception as exc:
            _LOGGER.error("Error in Heartbeat handler: %s", exc)
            return call_result.Heartbeat(current_time=self.coordinator.now())

    # ─────────────────────────────
    # Helper: Post-connect init
    # ─────────────────────────────

    async def _post_connect_init(self):
        try:
            await asyncio.sleep(1)

            self.coordinator.meterval_consecutive_timeouts = 0

            _LOGGER.info("🔄 Auto GetConfiguration after connect")
            await self.trigger_get_configuration()

            _LOGGER.info("Fetching external meter snapshot after connect")
            await self.trigger_external_meterval()

        except Exception as exc:
            _LOGGER.warning("Post-connect init failed: %s", exc)

    # ─────────────────────────────
    # Transactions
    # ─────────────────────────────

    @on("Authorize")
    async def on_authorize(self, id_tag, **kwargs):
        try:
            return call_result.Authorize(
                id_tag_info={"status": AuthorizationStatus.accepted}
            )
        except Exception as exc:
            _LOGGER.error("Error in Authorize handler for idTag=%s: %s", id_tag, exc, exc_info=True)
            return call_result.Authorize(
                id_tag_info={"status": AuthorizationStatus.invalid}
            )

    @on("StartTransaction")
    async def on_start_transaction(self, connector_id, id_tag, meter_start, **kwargs):
        try:
            transaction_id = self._transaction_id
            self._transaction_id += 1
            self.coordinator.start_transaction(
                transaction_id,
                id_tag,
                connector_id=connector_id,
                meter_start=meter_start,
                **kwargs,
            )
            return call_result.StartTransaction(
                transaction_id=transaction_id,
                id_tag_info={"status": AuthorizationStatus.accepted},
            )
        except Exception as exc:
            _LOGGER.error("Error in StartTransaction handler (connector=%s, idTag=%s): %s", connector_id, id_tag, exc, exc_info=True)
            return call_result.StartTransaction(
                transaction_id=0,
                id_tag_info={"status": AuthorizationStatus.invalid},
            )

    @on("StopTransaction")
    async def on_stop_transaction(self, transaction_id, meter_stop, reason=None, **kwargs):
        try:
            self.coordinator.stop_transaction(
                reason,
                transaction_id=transaction_id,
                meter_stop=meter_stop,
                **kwargs,
            )
            return call_result.StopTransaction(
                id_tag_info={"status": AuthorizationStatus.accepted}
            )
        except Exception as exc:
            _LOGGER.error("Error in StopTransaction handler (transaction_id=%s): %s", transaction_id, exc, exc_info=True)
            return call_result.StopTransaction(
                id_tag_info={"status": AuthorizationStatus.accepted}
            )

    # ─────────────────────────────
    # Status & Metering
    # ─────────────────────────────

    @on("StatusNotification")
    async def on_status_notification(self, connector_id, status, error_code=None, **kwargs):
        try:
            self.coordinator.record_status_notification(
                connector_id,
                status,
                error_code,
                **kwargs,
            )
            return call_result.StatusNotification()
        except Exception as exc:
            _LOGGER.error("Error in StatusNotification handler (status=%s): %s", status, exc, exc_info=True)
            return call_result.StatusNotification()

    @on("MeterValues")
    async def on_meter_values(self, connector_id, meter_value, **kwargs):
        try:
            transaction_id = kwargs.get('transaction_id')
            if transaction_id is not None:
                if self.coordinator.transaction_id != transaction_id:
                    self.coordinator.transaction_id = transaction_id
                    _LOGGER.info("✅ Transaction ID captured from MeterValues: %s", transaction_id)
                    self.coordinator.async_set_updated_data(True)
            self.coordinator.process_meter_values(meter_value)
            return call_result.MeterValues()
        except Exception as exc:
            _LOGGER.error("Error in MeterValues handler: %s", exc, exc_info=True)
            return call_result.MeterValues()

    # ─────────────────────────────
    # Growatt vendor DataTransfer
    # ─────────────────────────────

    @on("DataTransfer")
    async def on_data_transfer(self, vendor_id, message_id=None, data=None, **kwargs):
        try:
            _LOGGER.debug("DataTransfer received: vendor=%s messageId=%s data=%s", vendor_id, message_id, data)
            if isinstance(data, str) and message_id in ("frozenrecord", "currentrecord"):
                parsed = {k: v[0] for k, v in parse_qs(data).items()}
                _LOGGER.info("Parsed %s: %s", message_id, parsed)
                self.coordinator.process_frozen_record(parsed)
        except Exception as exc:
            _LOGGER.error("Error in DataTransfer handler (vendor=%s, messageId=%s): %s", vendor_id, message_id, exc, exc_info=True)
        return call_result.DataTransfer(status=DataTransferStatus.accepted)

    # ─────────────────────────────
    # Active triggers
    # ─────────────────────────────

    def _normalize_configuration_list(self, payload, field_name, call_name):
        if payload is None:
            _LOGGER.warning("%s returned no %s payload", call_name, field_name)
            return []

        if isinstance(payload, list):
            return payload

        if isinstance(payload, tuple):
            return list(payload)

        _LOGGER.warning(
            "%s returned unexpected %s type: %s",
            call_name,
            field_name,
            type(payload).__name__,
        )
        return []

    async def trigger_status(self):
        try:
            _LOGGER.info("Triggering StatusNotification")
            await self.call(call.TriggerMessage(requested_message="StatusNotification", connector_id=1))
        except Exception as exc:
            _LOGGER.warning("Failed to trigger StatusNotification: %s", exc)

    async def trigger_external_meterval(self):
        _LOGGER.info("Triggering Growatt get_external_meterval")

        task = asyncio.ensure_future(
            self.call(call.DataTransfer(vendor_id="Growatt", message_id="get_external_meterval"))
        )

        try:
            result = await asyncio.wait_for(asyncio.shield(task), timeout=15.0)

            self.coordinator.meterval_consecutive_timeouts = 0
            if hasattr(result, 'data') and isinstance(result.data, str):
                _LOGGER.info("Received external meter values: %s", result.data)
                self.coordinator.process_external_meter(result.data)
            else:
                _LOGGER.debug("External meterval result: %s", result)

        except asyncio.TimeoutError:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

            count = getattr(self.coordinator, 'meterval_consecutive_timeouts', 0) + 1
            self.coordinator.meterval_consecutive_timeouts = count

            if count >= 2:
                pause = min(60 * (count - 1), 300)
                until = self.hass.loop.time() + pause
                current = self.hass.data[DOMAIN].get("skip_polling_until", 0)
                self.hass.data[DOMAIN]["skip_polling_until"] = max(current, until)
                _LOGGER.debug(
                    "External meterval timeout #%d - pausing poll %ds (THOR likely rebooting)",
                    count, pause
                )
            else:
                _LOGGER.debug("External meterval timeout - THOR likely disconnected or busy")

        except websockets.exceptions.ConnectionClosedError as exc:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            _LOGGER.debug("External meterval aborted - connection closed: %s", exc)

        except Exception as exc:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            _LOGGER.warning("Failed to trigger external meter values: %s", exc)

    async def trigger_get_configuration(self):
        try:
            # ═══════════════════════════════════════════════════════
            # CALL 1: Operational keys
            # Keys actively used by the coordinator + essential OCPP
            # protocol keys. Explicit list keeps response small and
            # compatible with all THOR firmware variants (incl. 07AS)
            # ═══════════════════════════════════════════════════════

            operational_keys = list(OPERATIONAL_CONFIGURATION_KEYS)

            _LOGGER.info("Triggering GetConfiguration CALL 1 (operational keys: %d)", len(operational_keys))
            result1 = await asyncio.wait_for(
                self.call(call.GetConfiguration(key=operational_keys)),
                timeout=30.0
            )
            config_keys_1 = self._normalize_configuration_list(
                getattr(result1, "configuration_key", None),
                "configuration_key",
                "GetConfiguration CALL 1",
            )
            unknown_keys_1 = self._normalize_configuration_list(
                getattr(result1, "unknown_key", None),
                "unknown_key",
                "GetConfiguration CALL 1",
            )
            _LOGGER.info("CALL 1 received: %d keys (%d unknown)", len(config_keys_1), len(unknown_keys_1))

            # ═══════════════════════════════════════════════════════
            # CALL 2: Informational / diagnostic keys
            # Device info, network, solar, off-peak — display only
            # Capped at 30 keys (firmware hard limit per request)
            # G_WifiPassword intentionally excluded (security)
            # ═══════════════════════════════════════════════════════

            await asyncio.sleep(0.5)

            informational_keys = list(INFORMATIONAL_CONFIGURATION_KEYS)

            _LOGGER.info("Triggering GetConfiguration CALL 2 (informational keys: %d)", len(informational_keys))
            result2 = await asyncio.wait_for(
                self.call(call.GetConfiguration(key=informational_keys)),
                timeout=30.0
            )
            config_keys_2 = self._normalize_configuration_list(
                getattr(result2, "configuration_key", None),
                "configuration_key",
                "GetConfiguration CALL 2",
            )
            unknown_keys_2 = self._normalize_configuration_list(
                getattr(result2, "unknown_key", None),
                "unknown_key",
                "GetConfiguration CALL 2",
            )
            _LOGGER.info("CALL 2 received: %d keys (%d unknown)", len(config_keys_2), len(unknown_keys_2))

            # ═══════════════════════════════════════════════════════
            # Process all keys (call 1 + call 2)
            # ═══════════════════════════════════════════════════════

            all_config_keys = config_keys_1 + config_keys_2
            all_unknown_keys = normalize_unknown_configuration_keys(
                unknown_keys_1 + unknown_keys_2
            )
            _LOGGER.info("Total received: %d keys (%d unknown)", len(all_config_keys), len(all_unknown_keys))

            for item in all_config_keys:
                if not isinstance(item, dict):
                    _LOGGER.debug("Skipping unexpected configuration item type: %s", type(item).__name__)
                    continue

                key = item.get("key")
                value = item.get("value")
                readonly = item.get("readonly")
                _LOGGER.debug(
                    "Config key: %s = %s (readonly=%s)",
                    key,
                    redact_configuration_value(key, value),
                    readonly,
                )

            if all_unknown_keys:
                _LOGGER.info("Unknown keys: %s", ", ".join(str(k) for k in all_unknown_keys))

            if all_config_keys or all_unknown_keys:
                self.coordinator.process_configuration(
                    all_config_keys,
                    all_unknown_keys,
                )
            else:
                _LOGGER.warning("GetConfiguration returned no usable configuration keys")

        except asyncio.TimeoutError:
            _LOGGER.warning("GetConfiguration timeout - Thor likely rebooting, will retry on reconnect")
        except websockets.exceptions.ConnectionClosedError as exc:
            _LOGGER.debug("GetConfiguration aborted - connection closed: %s", exc)
        except Exception as exc:
            _LOGGER.warning("Failed to trigger GetConfiguration: %s", exc)

    # ─────────────────────────────
    # ChangeConfiguration
    # ─────────────────────────────

    async def change_configuration(self, key: str, value: str):
        try:
            _LOGGER.info(
                "ChangeConfiguration: %s = %s",
                key,
                redact_configuration_value(key, value),
            )
            result = await self.call(call.ChangeConfiguration(key=key, value=value))
            status = getattr(result, "status", ConfigurationStatus.rejected)
            _LOGGER.info("ChangeConfiguration result: %s", status)
            return status
        except Exception as exc:
            _LOGGER.error(
                "Failed to change configuration %s=%s: %s",
                key,
                redact_configuration_value(key, value),
                exc,
                exc_info=True,
            )
            return ConfigurationStatus.rejected

    # ─────────────────────────────
    # Remote Start/Stop Transaction
    # ─────────────────────────────

    async def remote_start_transaction(self, connector_id: int, id_tag: str) -> dict:
        try:
            _LOGGER.info("🔵 RemoteStartTransaction: connector_id=%d, id_tag=%s", connector_id, id_tag)
            result = await self.call(
                call.RemoteStartTransaction(connector_id=connector_id, id_tag=id_tag)
            )
            status = getattr(result, "status", RemoteStartStopStatus.rejected)
            _LOGGER.info("RemoteStartTransaction result: %s", status)
            return {"status": status.value if hasattr(status, "value") else str(status)}
        except Exception as exc:
            _LOGGER.error("Failed to start transaction: %s", exc, exc_info=True)
            return {"status": "Rejected"}

    async def remote_stop_transaction(self, transaction_id: int) -> dict:
        try:
            _LOGGER.info("🔴 RemoteStopTransaction: transaction_id=%d", transaction_id)
            result = await self.call(
                call.RemoteStopTransaction(transaction_id=transaction_id)
            )
            status = getattr(result, "status", RemoteStartStopStatus.rejected)
            _LOGGER.info("RemoteStopTransaction result: %s", status)
            return {"status": status.value if hasattr(status, "value") else str(status)}
        except Exception as exc:
            _LOGGER.error("Failed to stop transaction: %s", exc, exc_info=True)
            return {"status": "Rejected"}


# ─────────────────────────────
# WebSocket server
# ─────────────────────────────

async def _on_connect(websocket, path, coordinator, hass):
    watchdog_task = None
    try:
        if not path.startswith(DEFAULT_PATH):
            await websocket.close()
            return

        cp_id = path.rstrip("/").split("/")[-1]
        _LOGGER.info("THOR connected: %s", cp_id)
        cp = GrowattChargePoint(cp_id, websocket, coordinator, hass)
        watchdog_task = hass.async_create_task(cp.async_watch_connection())
        try:
            await cp.start()
        except (websockets.exceptions.ConnectionClosedError, websockets.exceptions.ConnectionClosedOK):
            _LOGGER.debug("Connection closed normally during startup - THOR disconnected")
        except Exception as exc:
            _LOGGER.error("Error in connection handler: %s", exc, exc_info=True)
        finally:
            if watchdog_task is not None:
                watchdog_task.cancel()
                try:
                    await watchdog_task
                except asyncio.CancelledError:
                    pass

            domain_data = hass.data.get(DOMAIN, {})
            if domain_data.get("charge_point") is cp:
                domain_data.pop("charge_point", None)
                coordinator.set_disconnected()
            else:
                _LOGGER.debug(
                    "Ignoring disconnect cleanup for superseded connection: %s",
                    cp_id,
                )
            try:
                await asyncio.wait_for(websocket.close(), timeout=5.0)
            except (asyncio.TimeoutError, Exception):
                pass

    except Exception as exc:
        _LOGGER.error("Error in connection handler: %s", exc, exc_info=True)
        try:
            await websocket.close()
        except Exception:
            pass


async def start_ocpp_server(host, port, coordinator, hass):
    try:
        _LOGGER.info("Starting OCPP server on %s:%s", host, port)

        await hass.async_add_executor_job(_preload_ocpp_schemas)

        return await serve(
            lambda ws, path: _on_connect(ws, path, coordinator, hass),
            host,
            port,
            subprotocols=[OCPP_SUBPROTOCOL],
            # THOR uses OCPP messages for keepalive; the activity watchdog
            # detects stale sockets without websocket-level ping futures.
            ping_interval=None,
            ping_timeout=None,
        )
    except Exception as exc:
        _LOGGER.error("Failed to start OCPP server: %s", exc, exc_info=True)
        raise
