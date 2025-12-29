"""Growatt THOR OCPP Integration for Home Assistant."""
import logging
import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.const import Platform

from .const import DOMAIN
from .coordinator import GrowattCoordinator
from .ocpp_server import start_ocpp_server

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.TIME,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Growatt THOR from config entry."""

    coordinator = GrowattCoordinator(hass)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["coordinator"] = coordinator

    # Start OCPP server
    host = entry.data.get("host", "0.0.0.0")
    port = entry.data.get("port", 9000)

    server = await start_ocpp_server(host, port, coordinator, hass)
    hass.data[DOMAIN]["server"] = server

    _LOGGER.info("OCPP server started on %s:%s", host, port)

    # Setup platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # ─────────────────────────────
    # 🔑 PERIODIC TASK: Elke 30s grid data ophalen
    # ─────────────────────────────

    async def periodic_external_meter_poll():
        """Poll external meter values every 1800 seconds."""
        # ✅ FIX: Eerste delay VOOR de loop zodat startup niet blokkeert
        await asyncio.sleep(1800)

        while True:
            charge_point = hass.data.get(DOMAIN, {}).get("charge_point")
            if charge_point:
                try:
                    _LOGGER.debug("Periodic: Triggering external meter values")
                    await charge_point.trigger_external_meterval()
                except Exception as exc:
                    _LOGGER.warning("Failed to trigger external meter values: %s", exc)

            # Wacht 1800s voor volgende poll
            await asyncio.sleep(1800)

    # Start periodic task (nu NON-BLOCKING)
    hass.data[DOMAIN]["polling_task"] = hass.async_create_background_task(
        periodic_external_meter_poll(),
        name="growatt_thor_periodic_poll"
    )

    # ─────────────────────────────
    # 🔑 MANUAL REFRESH SERVICE
    # ─────────────────────────────

    async def handle_refresh(call: ServiceCall):
        """Handle manual refresh service call."""
        charge_point = hass.data.get(DOMAIN, {}).get("charge_point")

        if not charge_point:
            _LOGGER.warning("No charge point connected - cannot refresh")
            return

        _LOGGER.debug("Manual refresh triggered")

        try:
            # 1. Status update
            _LOGGER.debug("Triggering StatusNotification")
            await charge_point.trigger_status()

            # 2. External meter values (GRID DATA)
            _LOGGER.debug("Triggering Growatt external meter values")
            await charge_point.trigger_external_meterval()

            # 3. Configuration
            _LOGGER.debug("Triggering Growatt GetConfiguration")
            await charge_point.trigger_get_configuration()

            _LOGGER.info("Manual refresh completed successfully")

        except Exception as exc:
            _LOGGER.error("Manual refresh failed: %s", exc, exc_info=True)

    hass.services.async_register(DOMAIN, "refresh", handle_refresh)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Growatt THOR config entry."""

    # Stop periodic polling
    polling_task = hass.data.get(DOMAIN, {}).get("polling_task")
    if polling_task:
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Stop OCPP server
    server = hass.data.get(DOMAIN, {}).get("server")
    if server:
        server.close()
        await server.wait_closed()

    # Remove services
    hass.services.async_remove(DOMAIN, "refresh")

    # Clean up
    if unload_ok:
        hass.data[DOMAIN].clear()

    return unload_ok

