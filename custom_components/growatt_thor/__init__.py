import asyncio
import logging

from .const import DOMAIN, DEFAULT_HOST, DEFAULT_PORT, CONF_HOST, CONF_PORT
from .coordinator import GrowattCoordinator
from .ocpp_server import start_ocpp_server

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry):
    coordinator = GrowattCoordinator(hass)

    server = await start_ocpp_server(
        host=entry.data.get(CONF_HOST, DEFAULT_HOST),
        port=entry.data.get(CONF_PORT, DEFAULT_PORT),
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
        await server.wait_closed()

    hass.data[DOMAIN].pop("server", None)
    hass.data[DOMAIN].pop("coordinator", None)
    return True

