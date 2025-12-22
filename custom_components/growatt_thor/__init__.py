import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    DEFAULT_HOST,
    DEFAULT_PORT,
    CONF_HOST,
    CONF_PORT,
)
from .coordinator import GrowattCoordinator
from .ocpp_server import start_ocpp_server

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Growatt THOR from a config entry."""

    coordinator = GrowattCoordinator(hass)
    await coordinator.async_config_entry_first_refresh()

    host = entry.data.get(CONF_HOST, DEFAULT_HOST)
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)

    server = await start_ocpp_server(
        host=host,
        port=port,
        coordinator=coordinator,
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["server"] = server
    hass.data[DOMAIN]["coordinator"] = coordinator

    # 🔑 Dit zorgt ervoor dat sensor.py echt wordt geladen
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info(
        "Growatt THOR OCPP server started on %s:%s",
        host,
        port,
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )

    server = hass.data.get(DOMAIN, {}).get("server")
    if server:
        server.close()
        await server.wait_closed()

    if unload_ok:
        hass.data[DOMAIN].pop("server", None)
        hass.data[DOMAIN].pop("coordinator", None)

    return unload_ok

