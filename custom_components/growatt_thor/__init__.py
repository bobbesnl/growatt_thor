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
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.storage import Store
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_POLL_INTERVAL,
    CONF_LOCATION,
    CONF_PORT,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
)
from .coordinator import GrowattCoordinator
from .ocpp_server import start_ocpp_server
from .runtime import GrowattRuntimeData, get_runtime_data, iter_runtime_data
from .session_csv import (
    SESSION_EXPORT_HEADERS,
    append_session_row,
    normalize_session_row,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.TIME,
    Platform.BUTTON,
]

SESSION_LOG_FILE = "growatt_thor_sessions.csv"

SERVICE_REFRESH = "refresh"
SERVICE_EXPORT_SESSIONS = "export_sessions"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"

TARGET_SCHEMA = vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string})

# Records which config entries existed when per-entry storage was introduced.
MIGRATION_STORAGE_KEY = "growatt_thor_migration"
MIGRATION_STORAGE_VERSION = 1


async def _legacy_seed_allowed(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Return whether this entry may inherit the shared legacy statistics.

    Before per-entry storage, all entries wrote one shared file. Only the
    entries that existed at the first start with per-entry storage inherit
    it; a charger added later starts with empty statistics. Concurrent
    setups write the same list, so the race between them is harmless.
    """
    store = Store(hass, MIGRATION_STORAGE_VERSION, MIGRATION_STORAGE_KEY)
    data = await store.async_load()
    if data is None:
        data = {
            "legacy_seed_entries": sorted(
                existing.entry_id
                for existing in hass.config_entries.async_entries(DOMAIN)
            )
        }
        await store.async_save(data)
    return entry.entry_id in data.get("legacy_seed_entries", [])


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


async def _check_existing_connection(coordinator):
    """Check if THOR is already connected and fetch current data."""
    await asyncio.sleep(2)

    charge_point = coordinator.active_charge_point
    if charge_point:
        _LOGGER.info("THOR already connected at startup, fetching current data")
        try:
            await charge_point.trigger_get_configuration()
            await charge_point.trigger_external_meterval()
        except Exception as exc:
            _LOGGER.debug("Could not fetch current data at startup: %s", exc)


def _get_session_log_path(hass):
    return hass.config.path(SESSION_LOG_FILE)


async def _append_session_to_csv(hass, session: dict):
    """Append a completed session to the CSV log."""
    path = _get_session_log_path(hass)

    def _write():
        append_session_row(path, session)

    await hass.async_add_executor_job(_write)
    _LOGGER.debug("📝 Session appended to CSV: %s", path)


async def _periodic_external_meter_poll(hass, entry_title, runtime):
    """Poll one entry's external meter while its charge point is connected."""
    coordinator = runtime.coordinator
    poll_interval = runtime.poll_interval

    await asyncio.sleep(poll_interval)

    _LOGGER.info(
        "External meter poll started for %s (interval: %ds)",
        entry_title,
        poll_interval,
    )
    skip_logged = False

    while True:
        try:
            current_time = hass.loop.time()
            skip_until = coordinator.skip_polling_until

            if current_time < skip_until:
                if not skip_logged:
                    _LOGGER.info(
                        "⏸️ Polling paused for %s (%ds remaining)",
                        entry_title,
                        int(skip_until - current_time),
                    )
                    skip_logged = True
                await asyncio.sleep(1)
                continue

            skip_logged = False
            charge_point = coordinator.active_charge_point

            if charge_point:
                _LOGGER.debug(
                    "Polling external meter for %s (%ds interval)",
                    entry_title,
                    poll_interval,
                )
                await charge_point.trigger_external_meterval()
            else:
                _LOGGER.debug(
                    "External meter poll skipped for %s: charger not connected",
                    entry_title,
                )

        except Exception as exc:
            _LOGGER.error("💥 Smart poll crashed: %s", exc, exc_info=True)

        await asyncio.sleep(poll_interval)


def _entry_title(hass, entry_id):
    entry = hass.config_entries.async_get_entry(entry_id)
    return entry.title if entry else entry_id


def _target_runtimes(hass, call: ServiceCall):
    """Return the loaded entries a service call targets (all by default)."""
    targets = iter_runtime_data(hass)
    entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if entry_id is None:
        return targets

    targets = [item for item in targets if item[0] == entry_id]
    if not targets:
        raise HomeAssistantError(
            f"Config entry {entry_id} is not a loaded Growatt THOR entry"
        )
    return targets


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the domain services once, shared by all config entries."""
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        return

    async def handle_refresh(call: ServiceCall):
        """Handle manual refresh service call."""
        for entry_id, runtime in _target_runtimes(hass, call):
            title = _entry_title(hass, entry_id)
            charge_point = runtime.coordinator.active_charge_point

            if not charge_point:
                _LOGGER.warning("%s: no charge point connected - cannot refresh", title)
                continue

            _LOGGER.debug("Manual refresh triggered for %s", title)

            try:
                await charge_point.trigger_status()
                await charge_point.trigger_external_meterval()
                await charge_point.trigger_get_configuration()
                _LOGGER.info("Manual refresh completed successfully for %s", title)

            except Exception as exc:
                _LOGGER.error("Manual refresh failed for %s: %s", title, exc, exc_info=True)

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
                            rows.append(normalize_session_row(row))
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

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH,
        handle_refresh,
        schema=TARGET_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT_SESSIONS,
        handle_export_sessions,
        schema=vol.Schema({
            vol.Required("date_from"): cv.string,
            vol.Required("date_to"): cv.string,
        }),
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Growatt THOR from config entry."""

    coordinator = GrowattCoordinator(
        hass,
        source_instance_id=entry.entry_id,
        seed_from_legacy=await _legacy_seed_allowed(hass, entry),
    )
    await coordinator.async_load_storage()

    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data["append_session_to_csv"] = lambda session: _append_session_to_csv(hass, session)

    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    coordinator.location = entry.data.get(CONF_LOCATION, "")

    poll_interval = entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
    _LOGGER.info("%s: configured grid poll interval: %d seconds", entry.title, poll_interval)

    runtime = GrowattRuntimeData(coordinator=coordinator, poll_interval=poll_interval)
    domain_data[entry.entry_id] = runtime

    try:
        runtime.server = await start_ocpp_server("0.0.0.0", port, coordinator, hass)
    except OSError as err:
        domain_data.pop(entry.entry_id, None)
        raise ConfigEntryNotReady(
            f"Cannot open OCPP port {port}: {err}"
        ) from err
    except Exception:
        domain_data.pop(entry.entry_id, None)
        raise

    _LOGGER.info("%s: OCPP server started on %s:%s", entry.title, "0.0.0.0", port)

    hass.async_create_task(_check_existing_connection(coordinator))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _migrate_external_meter_device(hass, entry)

    runtime.polling_task = hass.async_create_background_task(
        _periodic_external_meter_poll(hass, entry.title, runtime),
        name=f"growatt_thor_external_meter_poll_{entry.entry_id}",
    )

    _async_register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Growatt THOR config entry."""

    runtime = get_runtime_data(hass, entry.entry_id)

    if runtime and runtime.polling_task:
        runtime.polling_task.cancel()
        try:
            await runtime.polling_task
        except asyncio.CancelledError:
            pass

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if runtime and runtime.server:
        runtime.server.close()
        await runtime.server.wait_closed()
        runtime.server = None

    if unload_ok:
        domain_data = hass.data.get(DOMAIN, {})
        domain_data.pop(entry.entry_id, None)

        if not iter_runtime_data(hass):
            for service in (
                SERVICE_REFRESH,
                SERVICE_EXPORT_SESSIONS,
            ):
                hass.services.async_remove(DOMAIN, service)
            hass.data.pop(DOMAIN, None)

    return unload_ok
