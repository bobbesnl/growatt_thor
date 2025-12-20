import logging
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
        _LOGGER.info("BootNotification from %s: %s", self.id, kwargs)

        return {
            "currentTime": self.coordinator.now(),
            "interval": 60,
            "status": RegistrationStatus.accepted,
        }

    @on("StatusNotification")
    async def on_status_notification(self, status, **kwargs):
        _LOGGER.info("StatusNotification: %s", status)
        self.coordinator.set_status(status)

    @on("MeterValues")
    async def on_meter_values(self, meter_value, **kwargs):
        self.coordinator.process_meter_values(meter_value)


async def _on_connect(websocket, path, coordinator):
    if not path.startswith(DEFAULT_PATH):
        _LOGGER.warning("Rejected connection on path %s", path)
        await websocket.close()
        return

    cp_id = path.rstrip("/").split("/")[-1]
    _LOGGER.info("THOR connected with ChargePointId %s", cp_id)

    charge_point = GrowattChargePoint(cp_id, websocket, coordinator)
    await charge_point.start()


async def start_ocpp_server(host, port, coordinator):
    _LOGGER.info("Starting OCPP server on %s:%s", host, port)

    return await serve(
        lambda ws, path: _on_connect(ws, path, coordinator),
        host,
        port,
        subprotocols=[OCPP_SUBPROTOCOL],
    )

