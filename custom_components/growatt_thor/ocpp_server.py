"""OCPP Server implementation for Growatt THOR."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable, Awaitable

from websockets.server import serve
from websockets.legacy.server import WebSocketServerProtocol

from ocpp.v16 import ChargePoint as OcppChargePoint
from ocpp.v16.enums import RegistrationStatus, AuthorizationStatus
from ocpp.v16 import call_result
from ocpp.routing import on

from homeassistant.core import HomeAssistant

from .const import OCPP_SUBPROTOCOL, DEFAULT_PATH, DOMAIN

_LOGGER = logging.getLogger(__name__)


class GrowattChargePoint(OcppChargePoint):
    """OCPP 1.6j ChargePoint implementation for Growatt THOR."""

    def __init__(self, cp_id: str, websocket: WebSocketServerProtocol, coordinator: Any) -> None:
        """Initialize charge point wrapper."""
        super().__init__(cp_id, websocket)
        self.coordinator = coordinator
        self.coordinator.set_charge_point(cp_id)
        self._transaction_id: Optional[int] = None

    # 🔹 Boot
    @on("BootNotification")
    async def on_boot_notification(self, **kwargs: Any) -> call_result.BootNotificationPayload:
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
    async def on_heartbeat(self, **kwargs: Any) -> call_result.HeartbeatPayload:
        _LOGGER.debug("Heartbeat from %s", self.id)
        return call_result.HeartbeatPayload(
            currentTime=self.coordinator.now()
        )

    # 🔹 Status
    @on("StatusNotification")
    async def on_status_notification(
        self,
        connectorId: int,
        status: str,
        errorCode: str,
        timestamp: Optional[str] = None,
        **kwargs: Any,
    ) -> call_result.StatusNotificationPayload:
        _LOGGER.info(
            "StatusNotification %s: connector=%s status=%s error=%s",
            self.id,
            connectorId,
            status,
            errorCode,
        )
        self.coordinator.set_status(status)
        return call_result.StatusNotificationPayload()

    # 🔹 Authorize
    @on("Authorize")
    async def on_authorize(self, idTag: str, **kwargs: Any) -> call_result.AuthorizePayload:
        _LOGGER.info("Authorize request from %s idTag=%s", self.id, idTag)

        return call_result.AuthorizePayload(
            idTagInfo={"status": AuthorizationStatus.accepted}
        )

    # 🔹 StartTransaction
    @on("StartTransaction")
    async def on_start_transaction(
        self,
        connectorId: int,
        idTag: str,
        meterStart: int,
        timestamp: str,
        **kwargs: Any,
    ) -> call_result.StartTransactionPayload:
        # Local transaction id for HA-side
        self._transaction_id = int(datetime.now().timestamp())
        _LOGGER.info(
            "StartTransaction %s: connector=%s idTag=%s meterStart=%s",
            self.id,
            connectorId,
            idTag,
            meterStart,
        )

        # Inform coordinator
        self.coordinator.start_transaction(self._transaction_id, idTag)

        return call_result.StartTransactionPayload(
            transactionId=self._transaction_id,
            idTagInfo={"status": AuthorizationStatus.accepted},
        )

    # 🔹 StopTransaction
    @on("StopTransaction")
    async def on_stop_transaction(
        self,
        transactionId: int,
        meterStop: int,
        timestamp: str,
        reason: Optional[str] = None,
        **kwargs: Any,
    ) -> call_result.StopTransactionPayload:
        _LOGGER.info(
            "StopTransaction %s: transactionId=%s meterStop=%s reason=%s",
            self.id,
            transactionId,
            meterStop,
            reason,
        )
        self._transaction_id = None

        # Inform coordinator
        self.coordinator.stop_transaction(reason)

        return call_result.StopTransactionPayload()

    # 🔹 MeterValues (not commonly used by Growatt, but kept for compatibility)
    @on("MeterValues")
    async def on_meter_values(
        self,
        connectorId: int,
        meterValue: List[Dict[str, Any]],
        transactionId: Optional[int] = None,
        **kwargs: Any,
    ) -> call_result.MeterValuesPayload:
        self.coordinator.process_meter_values(meterValue)
        return call_result.MeterValuesPayload()

    # 🔹 DataTransfer (Growatt specific)
    @on("DataTransfer")
    async def on_data_transfer(
        self,
        vendorId: str,
        messageId: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> call_result.DataTransferPayload:
        _LOGGER.debug(
            "DataTransfer from %s vendor=%s messageId=%s data=%s",
            self.id,
            vendorId,
            messageId,
            data,
        )

        # Doorzetten naar coordinator voor verdere verwerking
        try:
            if messageId == "frozenrecord" and data:
                self.coordinator.process_frozen_record(data)
            elif messageId == "GetConfiguration" and data and "ConfigurationKey" in data:
                self.coordinator.process_configuration(data["ConfigurationKey"])
            elif messageId == "GetMeterValues" and data and "MeterValues" in data:
                self.coordinator.process_meter_values(data["MeterValues"])
        except Exception:
            _LOGGER.exception("Failed to process DataTransfer payload")

        return call_result.DataTransferPayload(status="Accepted")

    # ──────────────────────────────────────────────
    # Helper triggers used by HA service
    # ──────────────────────────────────────────────

    async def trigger_status(self) -> None:
        """Trigger a StatusNotification-like update (if supported via DataTransfer later)."""
        # Placeholder for future Growatt-specific polling via DataTransfer
        _LOGGER.debug("trigger_status() called - not yet implemented")

    async def trigger_external_meterval(self) -> None:
        """Trigger external meter value retrieval via vendor-specific DataTransfer."""
        _LOGGER.debug("trigger_external_meterval() called - not yet implemented")

    async def trigger_get_configuration(self) -> None:
        """Trigger GetConfiguration-like behavior via vendor-specific DataTransfer."""
        _LOGGER.debug("trigger_get_configuration() called - not yet implemented")


async def _on_connect(
    websocket: WebSocketServerProtocol,
    path: str,
    coordinator: Any,
    hass: HomeAssistant,
) -> None:
    """Handle incoming WebSocket OCPP connections."""
    from .const import DEFAULT_PATH as CP_PATH  # avoid circular import

    if not path.startswith(CP_PATH):
        _LOGGER.warning("Rejected connection on unexpected path: %s", path)
        await websocket.close()
        return

    parts = path.rstrip("/").split("/")
    cp_id = parts[-1] if len(parts) > 2 else "growatt_thor"

    _LOGGER.info("THOR connected with ChargePointId '%s'", cp_id)

    charge_point = GrowattChargePoint(cp_id, websocket, coordinator)

    # Bewaar charge_point zodat HA-services hem kunnen gebruiken
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["charge_point"] = charge_point

    try:
        await charge_point.start()
    except Exception as err:
        _LOGGER.exception("OCPP session error for %s: %s", cp_id, err)


async def start_ocpp_server(
    host: str,
    port: int,
    coordinator: Any,
    hass: HomeAssistant,
):
    """Start the OCPP WebSocket server for Growatt THOR."""
    _LOGGER.info("Starting OCPP server on %s:%s%s", host, port, DEFAULT_PATH)

    server = await serve(
        lambda ws, path: _on_connect(ws, path, coordinator, hass),
        host,
        port,
        subprotocols=[OCPP_SUBPROTOCOL],
    )

    return server

