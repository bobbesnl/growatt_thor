import logging
import asyncio
import websockets.exceptions
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
from .session_records import parse_growatt_session_record
from .ocpp_logging import OcppMetadataLogger
from .const import OCPP_SUBPROTOCOL, DEFAULT_PATH, DOMAIN
from .ocpp_requests import REQUEST_SKIPPED, SerializedOcppRequestGate
from .runtime_ownership import (
    ChargePointConnectionDecision,
    decide_charge_point_connection,
    release_active_charge_point,
)
from .write_queue import (
    ChargerConnectionUnavailable,
    ChargerRequestOutcomeUncertain,
)

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
        super().__init__(cp_id, websocket, logger=OcppMetadataLogger(_LOGGER, {}))

        self.coordinator = coordinator
        self.hass = hass
        self._cp_id = cp_id
        self._websocket = websocket
        self._activity = OcppConnectionActivity(hass.loop.time())
        self._boot_notification_requested = False
        self._outbound_requests = SerializedOcppRequestGate(
            connection_is_current=self._is_current_connection,
            connection_is_available=lambda: self.coordinator.connected,
            writes_are_pending=lambda: self.coordinator.has_pending_charger_writes,
            uncertain_transport_errors=(
                websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.ConnectionClosedOK,
            ),
        )

        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN]["charge_point"] = self

        self.coordinator.set_charge_point(cp_id)
        _LOGGER.info("GrowattChargePoint initialised for %s", cp_id)

    def _is_current_connection(self):
        """Return whether this charge point owns the active connection slot."""
        return self.hass.data.get(DOMAIN, {}).get("charge_point") is self

    def _connection_may_update_coordinator(self, operation_name: str) -> bool:
        """Allow state changes only from the socket that owns the runtime.

        A THOR reconnect can leave its old handler alive briefly.  Object
        identity, rather than the charger ID alone, distinguishes that stale
        socket from the replacement connection for the same physical charger.
        """
        if self._is_current_connection():
            return True
        _LOGGER.debug(
            "Ignoring %s from superseded connection for %s",
            operation_name,
            self._cp_id,
        )
        return False

    async def _run_serialized_request(
        self,
        operation_name,
        operation,
        *,
        skip_if_writes_pending=False,
        timeout_makes_outcome_uncertain=False,
    ):
        """Run one integration-initiated OCPP operation at a time.

        The OCPP library already serializes individual CALL frames, but that is
        too low-level for the THOR firmware.  A two-part GetConfiguration used
        to overlap logically with ChangeConfiguration and meter polling; the
        library then sent the waiting calls back-to-back.  Holding this lock for
        the complete logical operation prevents that burst and documents the
        firmware-protection boundary in one place.

        Incoming charger requests and their CALLRESULT responses do not use
        this lock.  Heartbeats must still be answered while an initiated CALL
        is waiting for the charger.
        """
        result = await self._outbound_requests.run(
            operation_name,
            operation,
            skip_if_writes_pending=skip_if_writes_pending,
            timeout_makes_outcome_uncertain=timeout_makes_outcome_uncertain,
        )
        if result is REQUEST_SKIPPED:
            _LOGGER.debug(
                "Skipping optional %s while a charger write is pending",
                operation_name,
            )
        return result

    def _mark_activity(self, action):
        """Record an inbound message for the connection watchdog."""
        self._activity.mark(self.hass.loop.time())
        if self._is_current_connection():
            self.coordinator.mark_connection_activity(action)

    async def route_message(self, raw_msg):
        """Track every inbound OCPP frame before routing it."""
        if not self._connection_may_update_coordinator("inbound OCPP frame"):
            return

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
                release_active_charge_point(domain_data, self)
            return

    # ─────────────────────────────
    # Boot / keepalive
    # ─────────────────────────────

    @on("BootNotification")
    async def on_boot_notification(self, **payload):
        if not self._connection_may_update_coordinator("BootNotification"):
            return call_result.BootNotification(
                current_time=self.coordinator.now(),
                interval=OCPP_HEARTBEAT_INTERVAL_SECONDS,
                status=RegistrationStatus.accepted,
            )
        try:
            _LOGGER.info("BootNotification payload: %s", payload)
            self.coordinator.record_boot_notification(payload)
            if not self._boot_notification_requested:
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
        if not self._connection_may_update_coordinator("Heartbeat"):
            return call_result.Heartbeat(current_time=self.coordinator.now())
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

            _LOGGER.info("🔄 Auto GetConfiguration after connect")
            await self.trigger_get_configuration()

            _LOGGER.info("Fetching external meter snapshot after connect")
            await self.trigger_external_meterval()

            if (
                self.coordinator.boot_notification is None
                and not self._boot_notification_requested
            ):
                self._boot_notification_requested = True
                await self.trigger_boot_notification()

        except Exception as exc:
            _LOGGER.warning("Post-connect init failed: %s", exc)

    # ─────────────────────────────
    # Transactions
    # ─────────────────────────────

    @on("Authorize")
    async def on_authorize(self, id_tag, **kwargs):
        if not self._connection_may_update_coordinator("Authorize"):
            return call_result.Authorize(
                id_tag_info={"status": AuthorizationStatus.invalid}
            )
        try:
            status = self.coordinator.authorization.decide(
                id_tag, "Authorize", self.coordinator.now()
            )
            _LOGGER.info("Local Authorize decision: %s", status)
            return call_result.Authorize(
                id_tag_info={"status": status}
            )
        except Exception:
            _LOGGER.error("Local Authorize failed; denying request")
            return call_result.Authorize(
                id_tag_info={"status": AuthorizationStatus.invalid}
            )

    @on("StartTransaction")
    async def on_start_transaction(self, connector_id, id_tag, meter_start, **kwargs):
        if not self._connection_may_update_coordinator("StartTransaction"):
            return call_result.StartTransaction(
                transaction_id=0,
                id_tag_info={"status": AuthorizationStatus.invalid},
            )
        try:
            # Even a denied start is a reported transaction. Allocate and retain
            # its identity so subsequent meter/stop messages remain correlatable.
            transaction_id = await self.coordinator.async_allocate_transaction_id()
            # ID allocation waits on a lock and therefore yields to a possible
            # reconnect.  Recheck ownership before committing transaction state
            # that would otherwise belong to the replacement socket.
            if not self._connection_may_update_coordinator(
                "StartTransaction after ID allocation"
            ):
                return call_result.StartTransaction(
                    transaction_id=0,
                    id_tag_info={"status": AuthorizationStatus.invalid},
                )
            # Authorization diagnostics and a one-shot HA Remote Start grant
            # are mutable coordinator-owned state.  Decide only after the
            # ownership recheck so a superseded socket cannot consume them.
            status = self.coordinator.authorization.decide(
                id_tag,
                "StartTransaction",
                self.coordinator.now(),
                # Plug & Charge is an explicit charger mode, not an RFID identity.
                card_policy_applies=str(
                    getattr(self.coordinator, "charger_mode", "")
                )
                != "3",
            )
            self.coordinator.start_transaction(
                transaction_id,
                id_tag,
                connector_id=connector_id,
                meter_start=meter_start,
                **kwargs,
            )
            self.coordinator.active_transaction["start"]["response"]["id_tag_info"] = {
                "status": status
            }
            _LOGGER.info("Local StartTransaction decision: %s", status)
            return call_result.StartTransaction(
                transaction_id=transaction_id,
                id_tag_info={"status": status},
            )
        except Exception:
            _LOGGER.error("StartTransaction handling failed; denying request")
            return call_result.StartTransaction(
                transaction_id=0,
                id_tag_info={"status": AuthorizationStatus.invalid},
            )

    @on("StopTransaction")
    async def on_stop_transaction(self, transaction_id, meter_stop, reason=None, **kwargs):
        if not self._connection_may_update_coordinator("StopTransaction"):
            return call_result.StopTransaction()
        try:
            self.coordinator.stop_transaction(
                reason,
                transaction_id=transaction_id,
                meter_stop=meter_stop,
                **kwargs,
            )
            # A stop must always be processed. Omit optional idTagInfo so this
            # acknowledgement does not grant cached access to an unknown tag.
            return call_result.StopTransaction()
        except Exception:
            _LOGGER.error("StopTransaction handling failed")
            return call_result.StopTransaction()

    # ─────────────────────────────
    # Status & Metering
    # ─────────────────────────────

    @on("StatusNotification")
    async def on_status_notification(self, connector_id, status, error_code=None, **kwargs):
        if not self._connection_may_update_coordinator("StatusNotification"):
            return call_result.StatusNotification()
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
        if not self._connection_may_update_coordinator("MeterValues"):
            return call_result.MeterValues()
        try:
            transaction_id = kwargs.get('transaction_id')
            if transaction_id is not None:
                if self.coordinator.transaction_id != transaction_id:
                    self.coordinator.transaction_id = transaction_id
                    _LOGGER.info("✅ Transaction ID captured from MeterValues: %s", transaction_id)
                    self.coordinator.async_set_updated_data(True)
            self.coordinator.process_meter_values(
                meter_value,
                connector_id=connector_id,
                transaction_id=transaction_id,
            )
            return call_result.MeterValues()
        except Exception as exc:
            _LOGGER.error("Error in MeterValues handler: %s", exc, exc_info=True)
            return call_result.MeterValues()

    # ─────────────────────────────
    # Growatt vendor DataTransfer
    # ─────────────────────────────

    @on("DataTransfer")
    async def on_data_transfer(self, vendor_id, message_id=None, data=None, **kwargs):
        if not self._connection_may_update_coordinator("DataTransfer"):
            return call_result.DataTransfer(status=DataTransferStatus.rejected)
        try:
            _LOGGER.debug("DataTransfer received: vendor=%s messageId=%s data=%s", vendor_id, message_id, data)
            if isinstance(data, str) and message_id in ("frozenrecord", "currentrecord"):
                record = parse_growatt_session_record(message_id, data)
                _LOGGER.info(
                    "Parsed %s for transaction %s",
                    message_id,
                    record.transaction_id,
                )
                self.coordinator.process_session_record(record)
            elif isinstance(data, str) and message_id == "faultmessage":
                self.coordinator.process_fault_message(vendor_id, data)
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
            await self._run_serialized_request(
                "TriggerMessage(StatusNotification)",
                lambda: self.call(
                    call.TriggerMessage(
                        requested_message="StatusNotification",
                        connector_id=1,
                    ),
                ),
            )
            return True
        except Exception as exc:
            _LOGGER.warning("Failed to trigger StatusNotification: %s", exc)
            return False

    async def trigger_boot_notification(self):
        """Request BootNotification when a reconnect did not send one."""
        try:
            _LOGGER.info("Triggering BootNotification for diagnostics")
            await self._run_serialized_request(
                "TriggerMessage(BootNotification)",
                lambda: self.call(
                    call.TriggerMessage(requested_message="BootNotification"),
                ),
            )
            return True
        except Exception as exc:
            _LOGGER.warning("Failed to trigger BootNotification: %s", exc)
            return False

    async def trigger_external_meterval(self, *, skip_if_writes_pending=False):
        _LOGGER.info("Triggering Growatt get_external_meterval")
        try:
            async def request_external_meter():
                task = asyncio.ensure_future(
                    self.call(
                        call.DataTransfer(
                            vendor_id="Growatt",
                            message_id="get_external_meterval",
                        ),
                    )
                )
                try:
                    return await asyncio.wait_for(asyncio.shield(task), timeout=15.0)
                except BaseException:
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
                    raise

            result = await self._run_serialized_request(
                "DataTransfer(get_external_meterval)",
                request_external_meter,
                skip_if_writes_pending=skip_if_writes_pending,
            )
            if result is REQUEST_SKIPPED:
                return False
            if not self._connection_may_update_coordinator(
                "external meter response"
            ):
                return False

            if hasattr(result, 'data') and isinstance(result.data, str):
                _LOGGER.info("Received external meter values: %s", result.data)
                if not self.coordinator.process_external_meter(result.data):
                    self.coordinator.record_external_meter_poll_timeout()
            else:
                self.coordinator.record_external_meter_poll_timeout()
                _LOGGER.warning("External meterval returned no usable data: %s", result)
            return True

        except asyncio.TimeoutError:
            if not self._connection_may_update_coordinator(
                "external meter timeout"
            ):
                return False
            self.coordinator.record_external_meter_poll_timeout()
            count = self.coordinator.meterval_consecutive_timeouts

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
            return False

        except (ChargerConnectionUnavailable, ChargerRequestOutcomeUncertain) as exc:
            _LOGGER.debug("External meterval aborted - connection closed: %s", exc)
            return False

        except Exception as exc:
            _LOGGER.warning("Failed to trigger external meter values: %s", exc)
            return False

    async def trigger_get_configuration(self, *, skip_if_writes_pending=False):
        """Read both configuration groups as one serialized operation."""
        try:
            result = await self._run_serialized_request(
                "GetConfiguration",
                self._request_configuration,
                skip_if_writes_pending=skip_if_writes_pending,
            )
            return result is not REQUEST_SKIPPED and bool(result)
        except (ChargerConnectionUnavailable, ChargerRequestOutcomeUncertain) as exc:
            _LOGGER.debug("GetConfiguration aborted - connection closed: %s", exc)
            return False

    async def _request_configuration(self):
        """Perform the two firmware-sized GetConfiguration calls."""
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
                self.call(
                    call.GetConfiguration(key=operational_keys),
                ),
                timeout=30.0
            )
            if not self._connection_may_update_coordinator(
                "GetConfiguration CALL 1 response"
            ):
                return False
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

            # Apply operational state immediately.  The second call contains
            # diagnostics and has historically been more likely to time out on
            # a busy THOR.  A timeout there must not discard a valid first
            # response or leave charging controls unknown.
            self.coordinator.process_configuration(
                config_keys_1,
                unknown_keys_1,
            )

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
                self.call(
                    call.GetConfiguration(key=informational_keys),
                ),
                timeout=30.0
            )
            if not self._connection_may_update_coordinator(
                "GetConfiguration CALL 2 response"
            ):
                return False
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
                # The first group was already applied above; process only the
                # new values while retaining the complete unknown-key view.
                self.coordinator.process_configuration(
                    config_keys_2,
                    all_unknown_keys,
                )
            else:
                _LOGGER.warning("GetConfiguration returned no usable configuration keys")
            return True

        except asyncio.TimeoutError:
            _LOGGER.warning("GetConfiguration timeout - Thor likely rebooting, will retry on reconnect")
            return False
        except (
            websockets.exceptions.ConnectionClosedError,
            websockets.exceptions.ConnectionClosedOK,
        ):
            # Let _run_serialized_request translate transport loss into the
            # shared reconnect semantics.
            raise
        except Exception as exc:
            _LOGGER.warning("Failed to trigger GetConfiguration: %s", exc)
            return False

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
            result = await self._run_serialized_request(
                f"ChangeConfiguration({key})",
                lambda: self.call(
                    call.ChangeConfiguration(key=key, value=value),
                ),
                timeout_makes_outcome_uncertain=True,
            )
            status = getattr(result, "status", ConfigurationStatus.rejected)
            _LOGGER.info("ChangeConfiguration result: %s", status)
            return status
        except (ChargerConnectionUnavailable, ChargerRequestOutcomeUncertain):
            # The queue distinguishes a definitely-unsent request from one
            # whose acknowledgement was lost.  Do not collapse either into an
            # ordinary charger rejection here.
            raise
        except Exception as exc:
            _LOGGER.error(
                "Failed to change configuration %s=%s: %s",
                key,
                redact_configuration_value(key, value),
                exc,
                exc_info=True,
            )
            return ConfigurationStatus.rejected

    async def send_data_transfer(
        self,
        *,
        vendor_id: str,
        message_id: str,
        data: str | None = None,
    ):
        """Send one vendor control payload and return its OCPP status."""
        try:
            _LOGGER.info(
                "DataTransfer control: vendor=%s messageId=%s",
                vendor_id,
                message_id,
            )
            payload = {
                "vendor_id": vendor_id,
                "message_id": message_id,
            }
            if data is not None:
                # OCPP marks ``data`` optional.  Omitting it is safer than
                # serializing JSON null for firmware commands such as AP mode.
                payload["data"] = data
            result = await self._run_serialized_request(
                f"DataTransfer({message_id})",
                lambda: self.call(
                    call.DataTransfer(**payload),
                ),
                timeout_makes_outcome_uncertain=True,
            )
            status = getattr(result, "status", DataTransferStatus.rejected)
            _LOGGER.info("DataTransfer control result: %s", status)
            return status
        except (ChargerConnectionUnavailable, ChargerRequestOutcomeUncertain):
            raise
        except Exception as exc:
            _LOGGER.error(
                "Failed DataTransfer control %s/%s: %s",
                vendor_id,
                message_id,
                exc,
                exc_info=True,
            )
            return DataTransferStatus.rejected

    # ─────────────────────────────
    # Remote Start/Stop Transaction
    # ─────────────────────────────

    async def remote_start_transaction(self, connector_id: int, id_tag: str) -> dict:
        authorization = self.coordinator.authorization
        try:
            if not authorization.begin_ha_remote_start(id_tag):
                _LOGGER.warning("Remote start denied by local authorisation policy")
                return {"status": "Rejected"}
            _LOGGER.info("RemoteStartTransaction: connector_id=%d", connector_id)
            result = await self._run_serialized_request(
                "RemoteStartTransaction",
                lambda: self.call(
                    call.RemoteStartTransaction(
                        connector_id=connector_id,
                        id_tag=id_tag,
                    ),
                ),
                timeout_makes_outcome_uncertain=True,
            )
            status = getattr(result, "status", RemoteStartStopStatus.rejected)
            status_value = status.value if hasattr(status, "value") else str(status)
            if status_value != RemoteStartStopStatus.accepted.value:
                authorization.cancel_ha_remote_start()
            _LOGGER.info("RemoteStartTransaction result: %s", status)
            return {"status": status_value}
        except ChargerConnectionUnavailable:
            authorization.cancel_ha_remote_start()
            raise
        except ChargerRequestOutcomeUncertain:
            # The THOR may have accepted the command before the response was
            # lost.  Keep the short-lived, one-shot grant so a resulting
            # StartTransaction is not incorrectly denied by local RFID policy.
            raise
        except Exception:
            authorization.cancel_ha_remote_start()
            _LOGGER.error("Failed to send remote start transaction")
            return {"status": "Rejected"}

    async def remote_stop_transaction(self, transaction_id: int) -> dict:
        try:
            _LOGGER.info("🔴 RemoteStopTransaction: transaction_id=%d", transaction_id)
            result = await self._run_serialized_request(
                "RemoteStopTransaction",
                lambda: self.call(
                    call.RemoteStopTransaction(transaction_id=transaction_id),
                ),
                timeout_makes_outcome_uncertain=True,
            )
            status = getattr(result, "status", RemoteStartStopStatus.rejected)
            _LOGGER.info("RemoteStopTransaction result: %s", status)
            return {"status": status.value if hasattr(status, "value") else str(status)}
        except (ChargerConnectionUnavailable, ChargerRequestOutcomeUncertain):
            raise
        except Exception as exc:
            _LOGGER.error("Failed to stop transaction: %s", exc, exc_info=True)
            return {"status": "Rejected"}


# ─────────────────────────────
# WebSocket server
# ─────────────────────────────

async def _close_superseded_connection(charge_point):
    """Close an old same-charger socket after its replacement owns the slot."""
    try:
        await asyncio.wait_for(
            charge_point._websocket.close(
                code=1000,
                reason="Superseded by a newer connection",
            ),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        _LOGGER.warning(
            "Timed out closing superseded connection for %s",
            charge_point._cp_id,
        )
        transport = getattr(charge_point._websocket, "transport", None)
        if transport is not None:
            transport.close()
    except Exception as exc:
        _LOGGER.debug(
            "Failed to close superseded connection for %s: %s",
            charge_point._cp_id,
            exc,
        )


async def _on_connect(websocket, path, coordinator, hass):
    watchdog_task = None
    cp = None
    try:
        if not path.startswith(DEFAULT_PATH):
            await websocket.close()
            return

        cp_id = path.rstrip("/").split("/")[-1]
        domain_data = hass.data.setdefault(DOMAIN, {})
        active_charge_point = domain_data.get("charge_point")
        active_charge_point_id = (
            getattr(active_charge_point, "_cp_id", "<unknown>")
            if active_charge_point is not None
            else None
        )
        decision = decide_charge_point_connection(
            retained_charge_point_id=coordinator.charge_point_id,
            active_charge_point_id=active_charge_point_id,
            incoming_charge_point_id=cp_id,
        )
        if (
            decision
            == ChargePointConnectionDecision.REJECT_DIFFERENT_CHARGER
        ):
            _LOGGER.error(
                "Rejecting OCPP connection from %s: runtime belongs to %s",
                cp_id,
                coordinator.charge_point_id or active_charge_point_id,
            )
            await websocket.close(
                code=1008,
                reason="A different charger already owns this integration",
            )
            return

        _LOGGER.info("THOR connected: %s", cp_id)
        cp = GrowattChargePoint(cp_id, websocket, coordinator, hass)
        if (
            decision
            == ChargePointConnectionDecision.REPLACE_SAME_CHARGER
        ):
            # Publish the replacement first.  The old handler's identity guard
            # then becomes effective before its socket is asked to close.
            hass.async_create_background_task(
                _close_superseded_connection(active_charge_point),
                name=f"growatt_thor_close_superseded_{cp_id}",
            )
        watchdog_task = hass.async_create_background_task(
            cp.async_watch_connection(),
            name=f"growatt_thor_connection_watchdog_{cp_id}",
        )
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
            if release_active_charge_point(domain_data, cp):
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
