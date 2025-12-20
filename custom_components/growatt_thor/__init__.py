import asyncio
import logging

from .const import DOMAIN, DEFAULT_PORT
from .coordinator import GrowattCoordinator
from .ocpp_server import start_ocpp_server

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry):
    coordinator = GrowattCoordinator(hass)

    server = await start_ocpp_server(
        host="0.0.0.0",
        port=entry.data.get("port", DEFAULT_PORT),
        coordinator=coordinator,
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["server"] = server
    hass.data[DOMAIN]["coordinator"] = coordinator

    _LOGGER.info("Growatt THOR OCPP server started")

    return True


async def async_unload_entry(hass, entry):
    server = hass.data[DOMAIN].get("server")
    if server:
        server.close()
    return True

