import logging
import asyncio
from websockets.server import serve
from ocpp.v16 import ChargePoint as OcppChargePoint
from ocpp.v16.enums import RegistrationStatus
from ocpp.routing import on

from .const import OCPP_SUBPROTOCOL, DEFAULT_PATH

_LOGGER = logging.getLogger(__name__)


class GrowattChargePoint(OcppChargePoint):
    def __init__(self, cp_id, websocket, coordinator):
        super().__init__(cp_id, websocket)
        self.coordinator = coordinator
        self.coordinator.set_charge_point(cp_id)

    @on("BootNotification")
    async def on_boot_notification(self, **kwargs):
        _LOGGER.info(
            "BootNotification from %s: chargePointModel=%s, chargePointVendor=%s",
            self.id,
            kwargs.get("chargePointModel"),
            kwargs.get("chargePointVendor"),
        )

        return {
            "currentTime": self.coordinator.now(),
            "interval": 60,
            "status": RegistrationStatus.accepted,
        }

    @on("StatusNotification")
    async def on_status_notification(self, status, **kwargs):
        _LOGGER.info("StatusNotification from %s: %s", self.id, status)
        self.coordinator.set_status(status)

        # OCPP verwacht een response, ook al is die leeg
        return {}

    @on("MeterValues")
    async def on_meter_values(self, meter_value, **kwargs):
        self.coordinator.process_meter_values(meter_value)
        return {}


async def _on_connect(websocket, path, coordinator):
    """
    Accepts:
    - /ocpp/ws
    - /ocpp/ws/<charge_point_id>

    Some Growatt THOR firmwares include the Charge Point ID in the URL,
    others do not. We support both.
    """
    if not path.startswith(DEFAULT_PATH):
        _LOGGER.warning("Rejected connection on unexpected path: %s", path)
        await websocket.close()
        return

    # Try to extract Charge Point ID from URL
    parts = path.rstrip("/").split("/")
    cp_id = parts[-1] if len(parts) > 2 else None

    if not cp_id or cp_id == "ws":
        # No ID provided in URL – use a temporary one
        cp_id = "growatt_thor"
        _LOGGER.info(
            "THOR connected without ChargePointId in URL, using default id '%s'",
            cp_id,
        )
    else:
        _LOGGER.info("THOR connected with ChargePointId '%s'", cp_id)

    charge_point = GrowattChargePoint(cp_id, websocket, coordinator)

    try:
        await charge_point.start()
    except Exception as err:
        _LOGGER.exception("OCPP session error for %s: %s", cp_id, err)


async def start_ocpp_server(host, port, coordinator):
    _LOGGER.info("Starting OCPP server on %s:%s%s", host, port, DEFAULT_PATH)

    server = await serve(
        lambda ws, path: _on_connect(ws, path, coordinator),
        host,
        port,
        subprotocols=[OCPP_SUBPROTOCOL],
    )

    return server

