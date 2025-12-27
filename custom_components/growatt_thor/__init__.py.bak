import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

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
    """Set up Growatt THOR from a config entry (push-based OCPP)."""

    coordinator = GrowattCoordinator(hass)

    host = entry.data.get(CONF_HOST, DEFAULT_HOST)
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)

    # BELANGRIJK: hass meegeven
    server = await start_ocpp_server(
        host=host,
        port=port,
        coordinator=coordinator,
        hass=hass,
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["server"] = server
    hass.data[DOMAIN]["coordinator"] = coordinator

    # ─────────────────────────────
    # Manual refresh service
    # ─────────────────────────────

    async def handle_refresh(call: ServiceCall) -> None:
        """Trigger actieve OCPP updates (Status + MeterValues)."""
        cp = hass.data.get(DOMAIN, {}).get("charge_point")

        if not cp:
            _LOGGER.warning("Growatt THOR refresh requested, but no charge point connected yet")
            return

        _LOGGER.info("Triggering OCPP refresh (StatusNotification + MeterValues)")

        try:
            await cp.trigger_status()
            await cp.trigger_meter_values()
        except Exception:
            _LOGGER.exception("Failed to trigger OCPP refresh")

    if not hass.services.has_service(DOMAIN, "refresh"):
        hass.services.async_register(
            DOMAIN,
            "refresh",
            handle_refresh,
        )

    # ─────────────────────────────
    # Load platforms (sensor.py)
    # ─────────────────────────────

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info(
        "Growatt THOR OCPP server started on %s:%s",
        host,
        port,
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Growatt THOR config entry."""

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
        hass.data[DOMAIN].pop("charge_point", None)

    return unload_ok
