"""Growatt THOR OCPP Integration for Home Assistant."""
import logging
import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.const import Platform

from .const import DOMAIN, CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
from .coordinator import GrowattCoordinator
from .ocpp_server import start_ocpp_server

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.TIME,
    Platform.BUTTON,
]

async def _check_existing_connection(hass, coordinator):
    """Check if THOR is already connected and fetch config."""
    await asyncio.sleep(2)

    charge_point = hass.data.get(DOMAIN, {}).get("charge_point")
    if charge_point:
        _LOGGER.info("THOR already connected at startup, fetching config...")
        try:
            await charge_point.trigger_get_configuration()
        except Exception as exc:
            _LOGGER.debug("Could not fetch config at startup: %s", exc)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Growatt THOR from config entry."""

    coordinator = GrowattCoordinator(hass)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["coordinator"] = coordinator
    hass.data[DOMAIN]["skip_polling_until"] = 0.0

    host = entry.data.get("host", "0.0.0.0")
    port = entry.data.get("port", 9000)
    
    # 🆕 Haal poll interval op uit config (met fallback naar default)
    poll_interval = entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
    hass.data[DOMAIN]["poll_interval"] = poll_interval
    
    _LOGGER.info("Configured grid poll interval: %d seconds", poll_interval)

    server = await start_ocpp_server(host, port, coordinator, hass)
    hass.data[DOMAIN]["server"] = server

    _LOGGER.info("OCPP server started on %s:%s", host, port)

    hass.async_create_task(_check_existing_connection(hass, coordinator))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def periodic_smart_grid_poll():
        """Smart poll: alleen als load balancing enabled."""
        # 🆕 Gebruik geconfigureerde poll interval ipv hardcoded waarde
        poll_interval = hass.data[DOMAIN].get("poll_interval", DEFAULT_POLL_INTERVAL)
        
        # Wacht eerst de poll interval voordat we beginnen
        await asyncio.sleep(poll_interval)
        
        _LOGGER.info("🚀 Smart poll task STARTED (interval: %ds)", poll_interval)
        loop = asyncio.get_event_loop()

        while True:
            try:
                skip_until = hass.data[DOMAIN].get("skip_polling_until", 0.0)
                current_time = loop.time()

                if current_time < skip_until:
                    # Log alleen de eerste keer dat we skippen
                    if not hasattr(periodic_smart_grid_poll, '_skip_logged') or not periodic_smart_grid_poll._skip_logged:
                        remaining = int(skip_until - current_time)
                        _LOGGER.info("⏸️ Polling paused (%ds remaining)", remaining)
                        periodic_smart_grid_poll._skip_logged = True
                    await asyncio.sleep(1)
                    continue
                else:
                    # Reset de flag als we weer aan het pollen zijn
                    periodic_smart_grid_poll._skip_logged = False

                charge_point = hass.data.get(DOMAIN, {}).get("charge_point")
                coordinator = hass.data.get(DOMAIN, {}).get("coordinator")

                if charge_point and coordinator:
                    if coordinator.external_limit_power_enable:
                        _LOGGER.debug("🔄 Smart poll (%ds): Load balancing ON → Grid data", poll_interval)
                        await charge_point.trigger_external_meterval()
                    else:
                        _LOGGER.debug("⏸️ Smart poll (%ds): Load balancing OFF → Skip", poll_interval)
                else:
                    _LOGGER.debug("⏸️ Smart poll (%ds): No charge_point or coordinator", poll_interval)

            except Exception as exc:
                _LOGGER.error("💥 Smart poll crashed: %s", exc, exc_info=True)

            # 🆕 Gebruik geconfigureerde poll interval
            await asyncio.sleep(poll_interval)

    hass.data[DOMAIN]["polling_task"] = hass.async_create_background_task(
        periodic_smart_grid_poll(),
        name="growatt_thor_smart_grid_poll"
    )

    async def handle_refresh(call: ServiceCall):
        """Handle manual refresh service call."""
        charge_point = hass.data.get(DOMAIN, {}).get("charge_point")

        if not charge_point:
            _LOGGER.warning("No charge point connected - cannot refresh")
            return

        _LOGGER.debug("Manual refresh triggered")

        try:
            _LOGGER.debug("Triggering StatusNotification")
            await charge_point.trigger_status()

            _LOGGER.debug("Triggering Growatt external meter values")
            await charge_point.trigger_external_meterval()

            _LOGGER.debug("Triggering Growatt GetConfiguration")
            await charge_point.trigger_get_configuration()

            _LOGGER.info("Manual refresh completed successfully")

        except Exception as exc:
            _LOGGER.error("Manual refresh failed: %s", exc, exc_info=True)

    hass.services.async_register(DOMAIN, "refresh", handle_refresh)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Growatt THOR config entry."""

    polling_task = hass.data.get(DOMAIN, {}).get("polling_task")
    if polling_task:
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    server = hass.data.get(DOMAIN, {}).get("server")
    if server:
        server.close()
        await server.wait_closed()

    hass.services.async_remove(DOMAIN, "refresh")

    if unload_ok:
        hass.data[DOMAIN].clear()

    return unload_ok

