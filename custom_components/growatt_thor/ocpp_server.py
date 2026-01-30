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
    RemoteStartStopStatus,
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
            transaction_id = kwargs.get('transaction_id')

            if transaction_id is not None:
                if self.coordinator.transaction_id != transaction_id:
                    self.coordinator.transaction_id = transaction_id
                    _LOGGER.info("✅ Transaction ID captured from MeterValues: %s", transaction_id)
                    self.coordinator.async_set_updated_data(True)

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

            if isinstance(data, str) and message_id in ("frozenrecord", "currentrecord"):
                parsed = {k: v[0] for k, v in parse_qs(data).items()}
                _LOGGER.info("Parsed %s: %s", message_id, parsed)
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
        """Haal configuratie op in 2 calls (standaard + extended)."""
        try:
            # ═══════════════════════════════════════════════════════
            # CALL 1: Standaard keys (Thor's default set)
            # ═══════════════════════════════════════════════════════

            _LOGGER.info("Triggering GetConfiguration CALL 1 (standard keys)")

            result1 = await asyncio.wait_for(
                self.call(call.GetConfigurationPayload()),  # Leeg = standaard keys
                timeout=30.0
            )

            config_keys_1 = getattr(result1, "configuration_key", [])
            unknown_keys_1 = getattr(result1, "unknown_key", [])

            _LOGGER.info("CALL 1 received: %d keys (%d unknown)", len(config_keys_1), len(unknown_keys_1))

            # ═══════════════════════════════════════════════════════
            # CALL 2: Extended keys (netwerk, WiFi, solar, off-peak)
            # ═══════════════════════════════════════════════════════

            # Kleine delay voor Thor stabiliteit
            await asyncio.sleep(0.5)

            extended_keys = [
                # Netwerk keys
                "G_ChargerNetDNS", "G_ChargerNetMask", "G_ChargerNetMac", "G_ChargerNetGateway",
                "G_NetworkMode",
                # WiFi keys
                "G_WifiSSID", "G_WifiPassword",
                # Tijd/datum keys
                "G_DaylightSavingTime", "G_PeriodTime",
                # Off-peak/tarief keys
                "G_OffPeakTime", "G_OffPeakEnable", "G_OffPeakCurr",
                # 4G/mobile keys
                "G_4GUserName", "G_4GPassword", "G_4GAPN",
                # Solar advanced keys
                "G_SolarBoost", "G_SolarThresholdCurr",
                # Meter/werkmodus keys
                "G_MeterValueInterval", "G_WorkingMode",
                # Overige keys
                "G_LowPowerReserveEnable", "UnlockConnectorOnEVSideDisconnect",
                "LightIntensity", "G_DRM3Percentage", "G_DRM4Percentage",
                # Nieuwe keys uit reverse engineering
                "G_LCDCloseEnable", "G_RFEnable"
            ]

            _LOGGER.info("Triggering GetConfiguration CALL 2 (extended keys: %d)", len(extended_keys))

            result2 = await asyncio.wait_for(
                self.call(call.GetConfigurationPayload(key=extended_keys)),
                timeout=30.0
            )

            config_keys_2 = getattr(result2, "configuration_key", [])
            unknown_keys_2 = getattr(result2, "unknown_key", [])

            _LOGGER.info("CALL 2 received: %d keys (%d unknown)", len(config_keys_2), len(unknown_keys_2))

            # ═══════════════════════════════════════════════════════
            # Verwerk alle keys (call 1 + call 2)
            # ═══════════════════════════════════════════════════════

            all_config_keys = config_keys_1 + config_keys_2
            all_unknown_keys = list(set(unknown_keys_1 + unknown_keys_2))

            _LOGGER.info("Total received: %d keys (%d unknown)", len(all_config_keys), len(all_unknown_keys))

            # Log alle keys (mask alleen WiFi password)
            for item in all_config_keys:
                key = item.get("key")
                value = item.get("value")
                readonly = item.get("readonly")

                # Mask alleen WiFi password
                if key == "G_WifiPassword":
                    value = "***MASKED***" if value else None

                _LOGGER.debug("Config key: %s = %s (readonly=%s)", key, value, readonly)

            # Log unknown keys als ze er zijn
            if all_unknown_keys:
                _LOGGER.info("Unknown keys: %s", ", ".join(all_unknown_keys))

            # Verwerk alle keys in coordinator
            self.coordinator.process_configuration(all_config_keys)

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
            _LOGGER.debug("Config change accepted!")

            return status

        except Exception as exc:
            _LOGGER.error("Failed to change configuration %s=%s: %s", key, value, exc, exc_info=True)
            return ConfigurationStatus.rejected

    # ─────────────────────────────
    # 🆕 Remote Start/Stop Transaction
    # ─────────────────────────────

    async def remote_start_transaction(self, connector_id: int, id_tag: str) -> dict:
        """Start een laadsessie via RemoteStartTransaction."""
        try:
            _LOGGER.info("🔵 RemoteStartTransaction: connector_id=%d, id_tag=%s", connector_id, id_tag)

            result = await self.call(
                call.RemoteStartTransactionPayload(
                    connector_id=connector_id,
                    id_tag=id_tag
                )
            )

            status = getattr(result, "status", RemoteStartStopStatus.rejected)
            _LOGGER.info("RemoteStartTransaction result: %s", status)

            return {"status": status.value if hasattr(status, "value") else str(status)}

        except Exception as exc:
            _LOGGER.error("Failed to start transaction: %s", exc, exc_info=True)
            return {"status": "Rejected"}

    async def remote_stop_transaction(self, transaction_id: int) -> dict:
        """Stop een laadsessie via RemoteStopTransaction."""
        try:
            _LOGGER.info("🔴 RemoteStopTransaction: transaction_id=%d", transaction_id)

            result = await self.call(
                call.RemoteStopTransactionPayload(
                    transaction_id=transaction_id
                )
            )

            status = getattr(result, "status", RemoteStartStopStatus.rejected)
            _LOGGER.info("RemoteStopTransaction result: %s", status)

            return {"status": status.value if hasattr(status, "value") else str(status)}

        except Exception as exc:
            _LOGGER.error("Failed to stop transaction: %s", exc, exc_info=True)
            return {"status": "Rejected"}


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

