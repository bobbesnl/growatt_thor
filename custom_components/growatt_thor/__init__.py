"""Growatt THOR OCPP Integration for Home Assistant."""
import logging
import asyncio
import csv
import os
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.const import Platform
from homeassistant.components.persistent_notification import async_create as pn_create
from homeassistant.helpers import device_registry as dr
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, CONF_POLL_INTERVAL, CONF_LOCATION, DEFAULT_POLL_INTERVAL
from .coordinator import GrowattCoordinator
from .ocpp_server import start_ocpp_server

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.TIME,
    Platform.BUTTON,
]

SESSION_LOG_FILE = "growatt_thor_sessions.csv"
SESSION_LOG_HEADERS = ["timestamp", "charger_id", "location", "start_time", "end_time", "energy_kwh", "cost", "duration_minutes", "transaction_id"]
SESSION_EXPORT_HEADERS = ["charger_id", "location", "start_time", "end_time", "energy_kwh", "cost", "duration_minutes", "transaction_id"]


def _migrate_external_meter_device(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update legacy default metadata for the external meter device."""
    registry = dr.async_get(hass)
    device = registry.async_get_device(
        identifiers={(DOMAIN, entry.entry_id, "grid_connection")}
    )
    if device is None:
        return

    changes = {}
    if device.name == "Growatt THOR Load balancing":
        changes["name"] = "Growatt THOR External Meter"
    if device.model == "THOR Load balancing":
        changes["model"] = "THOR External Meter"

    if changes:
        registry.async_update_device(device.id, **changes)


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


def _get_session_log_path(hass):
    return hass.config.path(SESSION_LOG_FILE)


async def _append_session_to_csv(hass, session: dict):
    """Append a completed session to the CSV log."""
    path = _get_session_log_path(hass)

    def _write():
        file_exists = os.path.isfile(path)
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=SESSION_LOG_HEADERS)
            if not file_exists:
                writer.writeheader()
            writer.writerow(session)

    await hass.async_add_executor_job(_write)
    _LOGGER.debug("📝 Session appended to CSV: %s", path)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Growatt THOR from config entry."""

    coordinator = GrowattCoordinator(hass)
    await coordinator.async_load_storage()
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["coordinator"] = coordinator
    hass.data[DOMAIN]["skip_polling_until"] = 0.0
    hass.data[DOMAIN]["append_session_to_csv"] = lambda session: _append_session_to_csv(hass, session)

    port = entry.data.get("port", 9000)
    coordinator.location = entry.data.get(CONF_LOCATION, "")

    poll_interval = entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
    hass.data[DOMAIN]["poll_interval"] = poll_interval

    _LOGGER.info("Configured grid poll interval: %d seconds", poll_interval)

    server = await start_ocpp_server("0.0.0.0", port, coordinator, hass)
    hass.data[DOMAIN]["server"] = server

    _LOGGER.info("OCPP server started on %s:%s", "0.0.0.0", port)

    hass.async_create_task(_check_existing_connection(hass, coordinator))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _migrate_external_meter_device(hass, entry)

    async def periodic_smart_grid_poll():
        """Smart poll: only when load balancing enabled."""
        poll_interval = hass.data[DOMAIN].get("poll_interval", DEFAULT_POLL_INTERVAL)

        await asyncio.sleep(poll_interval)

        _LOGGER.info("🚀 Smart poll task STARTED (interval: %ds)", poll_interval)
        loop = asyncio.get_event_loop()

        while True:
            try:
                skip_until = hass.data[DOMAIN].get("skip_polling_until", 0.0)
                current_time = loop.time()

                if current_time < skip_until:
                    if not hasattr(periodic_smart_grid_poll, '_skip_logged') or not periodic_smart_grid_poll._skip_logged:
                        remaining = int(skip_until - current_time)
                        _LOGGER.info("⏸️ Polling paused (%ds remaining)", remaining)
                        periodic_smart_grid_poll._skip_logged = True
                    await asyncio.sleep(1)
                    continue
                else:
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
            await charge_point.trigger_status()
            await charge_point.trigger_external_meterval()
            await charge_point.trigger_get_configuration()
            _LOGGER.info("Manual refresh completed successfully")

        except Exception as exc:
            _LOGGER.error("Manual refresh failed: %s", exc, exc_info=True)

    async def handle_export_sessions(call: ServiceCall):
        """Export sessions within a date range to a separate CSV."""
        date_from_str = call.data.get("date_from")
        date_to_str = call.data.get("date_to")

        try:
            date_from = datetime.strptime(date_from_str, "%Y-%m-%d")
            date_to = datetime.strptime(date_to_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        except ValueError:
            _LOGGER.error("Invalid date format. Use YYYY-MM-DD")
            return

        source_path = _get_session_log_path(hass)
        export_filename = f"growatt_thor_export_{date_from_str}_{date_to_str}.csv"
        www_path = hass.config.path("www")
        export_path = os.path.join(www_path, export_filename)

        def _export():
            os.makedirs(www_path, exist_ok=True)

            if not os.path.isfile(source_path):
                return 0

            rows = []
            with open(source_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        row_date = datetime.strptime(row["start_time"], "%Y-%m-%d %H:%M:%S")
                        if date_from <= row_date <= date_to:
                            rows.append(row)
                    except (ValueError, KeyError):
                        continue

            with open(export_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=SESSION_EXPORT_HEADERS, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)

            return len(rows)

        count = await hass.async_add_executor_job(_export)

        pn_create(
            hass,
            f"Export klaar: **{count} sessies** van {date_from_str} t/m {date_to_str}\n\n"
            f"[⬇️ Download CSV](/local/{export_filename})",
            title="Growatt THOR sessie-export",
            notification_id="growatt_thor_export",
        )
        _LOGGER.info("Session export: %d rows written to %s", count, export_path)

    hass.services.async_register(DOMAIN, "refresh", handle_refresh)
    hass.services.async_register(
        DOMAIN,
        "export_sessions",
        handle_export_sessions,
        schema=vol.Schema({
            vol.Required("date_from"): cv.string,
            vol.Required("date_to"): cv.string,
        }),
    )

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
    hass.services.async_remove(DOMAIN, "export_sessions")

    if unload_ok:
        hass.data[DOMAIN].clear()

    return unload_ok
