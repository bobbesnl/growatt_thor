"""Growatt THOR OCPP Integration for Home Assistant."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import TYPE_CHECKING

import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .charging.authorization import CONF_AUTHORIZATION, LocalAuthorization
from .charging.pv_service import (
    async_register_pv_linkage_service,
    async_setup_pv_linkage_service,
    async_unload_pv_linkage_service,
)
from .configuration.validation import (
    validate_bind_address,
    validate_poll_interval,
    validate_tcp_port,
)
from .const import (
    CONF_LOCATION,
    CONF_POLL_INTERVAL,
    CONF_PORT,
    CONFIG_ENTRY_VERSION,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
    DOMAIN,
    MIN_POLL_INTERVAL,
    SESSION_LOG_FILE,
)
from .coordinator import GrowattCoordinator
from .energy.options import CONF_BATTERY_POWER_ENTITY, CONF_BATTERY_POWER_SIGN
from .energy.sources import BATTERY_POSITIVE_DISCHARGE
from .energy.stop_guard import EnergyStopGuard
from .ocpp.server import start_ocpp_server
from .presentation.frontend import async_register_frontend
from .runtime.entity_migrations import (
    LEGACY_SESSION_DURATION_UNIT_MIGRATION,
    PENDING_EXTERNAL_METER_READBACK_MIGRATION,
    disable_redundant_external_meter_readbacks,
    migrate_session_duration_unit,
)
from .runtime.keys import (
    ACTIVE_CHARGE_POINT,
    APPEND_SESSION_TO_CSV,
    COORDINATOR,
    ENERGY_STOP_GUARD,
    OWNS_LEGACY_HISTORY,
    PERSIST_CHARGER_IDENTITY,
    POLL_INTERVAL,
    POLL_INTERVAL_SCHEDULE,
    POLLING_TASK,
    REFRESH_DASHBOARD,
    SERVER,
    SESSION_HISTORY_UNSUB,
    SKIP_POLLING_UNTIL,
    STARTUP_CHECK_TASK,
    UPDATE_SESSION_EVENTS_IN_CSV,
)
from .runtime.ownership import (
    claim_entry_runtime,
    entry_runtime_data,
    release_entry_runtime,
)
from .runtime.polling import ExternalMeterPoller, PollIntervalSchedule
from .runtime.service_setup import async_register_services
from .sessions.csv import (
    append_session_row,
    update_session_events,
)
from .sessions.dashboard import async_refresh_dashboard
from .sessions.exports import ensure_export_cleanup
from .sessions.telemetry import async_setup_session_history
from .sessions.websocket import async_register_session_websocket
from .targets.services import (
    async_register_target_services,
    async_setup_target_services,
    async_unload_target_services,
)
from .timestamps import installation_time_zone

if TYPE_CHECKING:
    from .runtime.entry import ThorConfigEntry


_LOGGER = logging.getLogger(__name__)

# async_setup registers shared services and assets; configuration uses the UI flow.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.TIME,
    Platform.BUTTON,
]

# Records which config entries existed when per-entry storage was introduced.
MIGRATION_STORAGE_KEY = "growatt_thor_migration"
MIGRATION_STORAGE_VERSION = 1


async def _legacy_seed_allowed(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Return whether this entry may inherit the shared legacy statistics.

    Before per-entry storage, all entries wrote one shared file.  Only the
    entries that existed at the first start with per-entry storage inherit
    it; a charger added later starts with empty statistics.  Concurrent
    setups write the same list, so the race between them is harmless.
    """
    store = Store(hass, MIGRATION_STORAGE_VERSION, MIGRATION_STORAGE_KEY)
    data = await store.async_load()
    if data is None:
        data = {
            "legacy_seed_entries": sorted(
                existing.entry_id for existing in hass.config_entries.async_entries(DOMAIN)
            )
        }
        await store.async_save(data)
    return entry.entry_id in data.get("legacy_seed_entries", [])


async def _owns_legacy_history(hass, entry):
    """Only an unambiguous pre-upgrade entry may inherit unlabelled totals."""
    data = await Store(hass, MIGRATION_STORAGE_VERSION, MIGRATION_STORAGE_KEY).async_load()
    return bool(data and data.get("legacy_seed_entries") == [entry.entry_id])


async def async_migrate_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Migrate legacy entity-registry settings for an existing entry."""
    if entry.version > CONFIG_ENTRY_VERSION:
        _LOGGER.error(
            "Cannot migrate config entry from version %s to %s",
            entry.version,
            CONFIG_ENTRY_VERSION,
        )
        return False

    has_legacy_marker = bool(entry.data.get(LEGACY_SESSION_DURATION_UNIT_MIGRATION))
    if entry.version < CONFIG_ENTRY_VERSION or has_legacy_marker:
        registry = er.async_get(hass)
        if migrate_session_duration_unit(registry, entry.entry_id):
            _LOGGER.info("Migrated last-session duration display from min to h")

        migrated_data = dict(entry.data)
        migrated_data.pop(LEGACY_SESSION_DURATION_UNIT_MIGRATION, None)
        if entry.version < CONFIG_ENTRY_VERSION:
            migrated_data[PENDING_EXTERNAL_METER_READBACK_MIGRATION] = True
        hass.config_entries.async_update_entry(
            entry,
            data=migrated_data,
            version=CONFIG_ENTRY_VERSION,
        )

    return True


async def _recover_pending_entity_migrations(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Recover a duration migration marker written by an earlier dev build."""
    if not entry.data.get(LEGACY_SESSION_DURATION_UNIT_MIGRATION):
        return

    registry = er.async_get(hass)
    if migrate_session_duration_unit(registry, entry.entry_id):
        _LOGGER.info("Recovered last-session duration display migration")

    migrated_data = dict(entry.data)
    migrated_data.pop(LEGACY_SESSION_DURATION_UNIT_MIGRATION, None)
    hass.config_entries.async_update_entry(entry, data=migrated_data)


def _complete_external_meter_readback_migration(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Disable redundant readbacks after entity setup loads the registry."""
    if not entry.data.get(PENDING_EXTERNAL_METER_READBACK_MIGRATION):
        return

    registry = er.async_get(hass)
    disabled_readbacks = disable_redundant_external_meter_readbacks(
        registry,
        entry.entry_id,
        er.RegistryEntryDisabler.INTEGRATION,
    )
    if disabled_readbacks:
        _LOGGER.info(
            "Disabled redundant External Meter readback entities: %s",
            ", ".join(disabled_readbacks),
        )

    migrated_data = dict(entry.data)
    migrated_data.pop(PENDING_EXTERNAL_METER_READBACK_MIGRATION, None)
    hass.config_entries.async_update_entry(entry, data=migrated_data)


def _migrate_external_meter_device(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update legacy default metadata for the external meter device."""
    registry = dr.async_get(hass)
    device = registry.async_get_device_by_identifier(
        # Keep the legacy identifier so the existing device is updated in place.
        (DOMAIN, entry.entry_id, "grid_connection"),
        entry.entry_id,
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
    """Check if THOR is already connected and fetch current data."""
    await asyncio.sleep(2)

    charge_point = coordinator.runtime_data.get(ACTIVE_CHARGE_POINT)
    if charge_point:
        _LOGGER.info("THOR already connected at startup, fetching current data")
        try:
            await charge_point.trigger_get_configuration()
            await charge_point.trigger_external_meterval()
        except Exception as exc:
            _LOGGER.debug("Could not fetch current data at startup: %s", exc)


def _get_session_log_path(hass):
    return hass.config.path(SESSION_LOG_FILE)


async def _append_session_to_csv(hass, coordinator, session: dict):
    """Append a completed session to the CSV log."""
    path = _get_session_log_path(hass)

    def _write():
        append_session_row(path, session)

    await hass.async_add_executor_job(_write)
    if coordinator is not None:
        await async_refresh_dashboard(hass, coordinator, path)


async def _update_session_events_in_csv(
    hass,
    coordinator,
    session_id: str,
    events: list[dict[str, str]],
) -> None:
    """Persist late session events such as unplugging after transaction stop."""
    path = _get_session_log_path(hass)
    updated = await hass.async_add_executor_job(
        update_session_events,
        path,
        session_id,
        events,
    )
    if not updated:
        return
    if coordinator is not None:
        await async_refresh_dashboard(hass, coordinator, path)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register integration-level services independently from config entries."""
    async_register_services(hass)
    ensure_export_cleanup(hass)

    await async_register_frontend(hass)
    async_register_pv_linkage_service(hass)
    async_register_target_services(hass)
    async_register_session_websocket(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ThorConfigEntry) -> bool:
    """Set up Growatt THOR from config entry."""

    # Every config entry owns its own runtime (see runtime_ownership): a
    # second charger is a second entry and never replaces the first one.
    domain_data = hass.data.setdefault(DOMAIN, {})
    runtime_data = claim_entry_runtime(domain_data, entry.entry_id)
    if runtime_data is None:
        _LOGGER.error(
            "Cannot set up config entry %s: it already has a loaded runtime",
            entry.entry_id,
        )
        return False

    try:
        await _recover_pending_entity_migrations(hass, entry)

        coordinator = await _create_coordinator(hass, entry, runtime_data)

        server, bind_address, port = await _start_server(hass, entry, coordinator, runtime_data)
        poll_interval_schedule = runtime_data[POLL_INTERVAL_SCHEDULE]
    except BaseException:
        # A failed setup must release its claim or every future retry would be
        # mistaken for an entry that is already loaded.  No server-owned tasks
        # exist yet when this path runs successfully through the cleanup
        # boundary above.
        release_entry_runtime(domain_data, entry.entry_id, runtime_data)
        raise

    _LOGGER.info("%s: OCPP server started on %s:%s", entry.title, bind_address, port)

    startup_check_task = hass.async_create_background_task(
        _check_existing_connection(hass, coordinator),
        name=f"growatt_thor_startup_connection_check_{entry.entry_id}",
    )

    runtime_data[STARTUP_CHECK_TASK] = startup_check_task

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        _complete_external_meter_readback_migration(hass, entry)
        _migrate_external_meter_device(hass, entry)
    except Exception:
        startup_check_task.cancel()
        with suppress(asyncio.CancelledError):
            await startup_check_task
        server.close()
        await server.wait_closed()
        release_entry_runtime(domain_data, entry.entry_id, runtime_data)
        raise

    await _start_background_tasks(hass, entry, coordinator, runtime_data, poll_interval_schedule)
    return True


async def _create_coordinator(hass, entry, runtime_data):
    coordinator = GrowattCoordinator(
        hass,
        source_instance_id=entry.entry_id,
        seed_from_legacy=await _legacy_seed_allowed(hass, entry),
    )
    entry.runtime_data = runtime_data
    coordinator.runtime_data = runtime_data
    coordinator.charge_point_id = entry.data.get("charge_point_id")

    def persist_charger_identity(cp_id):
        if entry.data.get("charge_point_id") != cp_id:
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, "charge_point_id": cp_id}
            )

    runtime_data[PERSIST_CHARGER_IDENTITY] = persist_charger_identity
    runtime_data[OWNS_LEGACY_HISTORY] = await _owns_legacy_history(hass, entry)
    coordinator.authorization = LocalAuthorization(entry.data.get(CONF_AUTHORIZATION))
    coordinator.battery_power_entity = entry.data.get(CONF_BATTERY_POWER_ENTITY)
    coordinator.battery_power_sign = entry.data.get(
        CONF_BATTERY_POWER_SIGN,
        BATTERY_POSITIVE_DISCHARGE,
    )
    coordinator.site_accounting_options = dict(entry.data)
    await coordinator.async_load_storage()
    runtime_data[COORDINATOR] = coordinator
    runtime_data[SKIP_POLLING_UNTIL] = 0.0
    runtime_data[APPEND_SESSION_TO_CSV] = lambda session: _append_session_to_csv(
        hass, coordinator, session
    )
    runtime_data[UPDATE_SESSION_EVENTS_IN_CSV] = lambda session_id, events: (
        _update_session_events_in_csv(hass, coordinator, session_id, events)
    )
    # Replay checkpointed completions before loading the dashboard summary.
    # Otherwise a restart could show history from before a recovered CSV append.
    await coordinator.sessions.async_flush_pending()
    session_log_path = _get_session_log_path(hass)

    async def refresh_dashboard():
        await async_refresh_dashboard(
            hass,
            coordinator,
            session_log_path,
            retain=True,
            time_zone=installation_time_zone(hass),
        )

    runtime_data[REFRESH_DASHBOARD] = refresh_dashboard
    await refresh_dashboard()

    return coordinator


async def _start_server(hass, entry, coordinator, runtime_data):
    # Revalidate persisted entries as well as form submissions.  This
    # covers older or manually altered storage before opening a socket or
    # starting a poll loop with an unusable value.
    port = validate_tcp_port(entry.data.get(CONF_PORT, DEFAULT_PORT))
    coordinator.location = entry.data.get(CONF_LOCATION, "")

    poll_interval = validate_poll_interval(
        entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        minimum=MIN_POLL_INTERVAL,
    )
    coordinator.external_meter_poll_interval = poll_interval
    runtime_data[POLL_INTERVAL] = poll_interval
    poll_interval_schedule = PollIntervalSchedule(poll_interval)
    runtime_data[POLL_INTERVAL_SCHEDULE] = poll_interval_schedule

    _LOGGER.info(
        "%s: configured grid poll interval: %d seconds",
        entry.title,
        poll_interval,
    )

    bind_address = validate_bind_address(entry.data.get("bind_address", "0.0.0.0"))
    try:
        server = await start_ocpp_server(bind_address, port, coordinator, hass)
    except OSError as err:
        # Typically the port is still held by a server that is shutting
        # down.  Let Home Assistant retry instead of failing permanently.
        raise ConfigEntryNotReady(f"Cannot open OCPP port {port}: {err}") from err
    runtime_data[SERVER] = server
    return server, bind_address, port


async def _start_background_tasks(hass, entry, coordinator, runtime_data, poll_interval_schedule):
    poller = ExternalMeterPoller(runtime_data, poll_interval_schedule)
    runtime_data[POLLING_TASK] = hass.async_create_background_task(
        poller.run(),
        name=f"growatt_thor_external_meter_poll_{entry.entry_id}",
    )

    await async_setup_pv_linkage_service(hass, entry, coordinator)
    await async_setup_target_services(hass, entry, coordinator)
    runtime_data[ENERGY_STOP_GUARD] = EnergyStopGuard(hass, coordinator)
    runtime_data[ENERGY_STOP_GUARD].refresh()
    runtime_data[SESSION_HISTORY_UNSUB] = async_setup_session_history(hass, coordinator)


async def async_unload_entry(hass: HomeAssistant, entry: ThorConfigEntry) -> bool:
    """Unload Growatt THOR config entry."""

    domain_data = hass.data.get(DOMAIN, {})
    runtime_data = entry_runtime_data(domain_data, entry.entry_id)
    if runtime_data is None:
        # An entry without a loaded runtime has nothing to tear down, and it
        # must never touch the server or coordinator of another entry.
        _LOGGER.warning(
            "Ignoring unload for config entry %s without a loaded runtime",
            entry.entry_id,
        )
        return True

    # Unload the entities first.  When that does not succeed Home Assistant
    # keeps the entry loaded, so its poll loop, write queue and OCPP server
    # must keep running instead of leaving entities without a charger.
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        _LOGGER.warning(
            "Unloading the platforms of config entry %s failed; keeping its "
            "charger connection running",
            entry.entry_id,
        )
        return False

    startup_task = runtime_data.get(STARTUP_CHECK_TASK)
    if startup_task is not None:
        startup_task.cancel()
        with suppress(asyncio.CancelledError):
            await startup_task

    polling_task = runtime_data.get(POLLING_TASK)
    if polling_task:
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass

    energy_stop_guard = runtime_data.get(ENERGY_STOP_GUARD)
    if energy_stop_guard is not None:
        await energy_stop_guard.async_shutdown()

    if stop_history := runtime_data.get(SESSION_HISTORY_UNSUB):
        stop_history()

    coordinator = runtime_data.get(COORDINATOR)
    if coordinator is not None:
        # The write queue may intentionally be waiting for a reconnect.  Stop
        # that wait before releasing the runtime so no background task
        # survives a reload of the integration.
        await coordinator.async_shutdown()

    server = runtime_data.get(SERVER)
    if server:
        server.close()
        await server.wait_closed()

    async_unload_pv_linkage_service(hass, entry)
    async_unload_target_services(hass, entry)
    release_entry_runtime(domain_data, entry.entry_id, runtime_data)
    return True
