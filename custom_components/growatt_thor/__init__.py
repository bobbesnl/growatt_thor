"""Growatt THOR OCPP Integration for Home Assistant."""

import asyncio
import logging
from contextlib import suppress
from pathlib import Path

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.persistent_notification import async_create as pn_create
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .configuration.validation import (
    DateRangeValidationError,
    DateRangeValidationReason,
    parse_export_date_range,
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
)
from .coordinator import GrowattCoordinator
from .energy.sources import (
    BATTERY_POSITIVE_DISCHARGE,
    CONF_BATTERY_POWER_ENTITY,
    CONF_BATTERY_POWER_SIGN,
)
from .ocpp.server import start_ocpp_server
from .runtime.action_errors import (
    raise_action_validation,
    raise_charger_disconnected,
    raise_communication_error,
)
from .runtime.entity_migrations import (
    LEGACY_SESSION_DURATION_UNIT_MIGRATION,
    PENDING_EXTERNAL_METER_READBACK_MIGRATION,
    disable_redundant_external_meter_readbacks,
    migrate_session_duration_unit,
)
from .runtime.ownership import (
    claim_entry_runtime,
    entry_runtime_data,
    loaded_entry_runtimes,
    release_entry_runtime,
)
from .runtime.polling import PollIntervalSchedule
from .runtime.services import (
    ChargerServiceUnavailable,
    IntegrationServiceOperations,
    ManualRefreshFailed,
)
from .runtime.time import installation_time_zone
from .sessions.csv import (
    append_session_row,
    dashboard_session_data,
    enforce_session_retention,
    export_session_rows,
    update_session_events,
)
from .sessions.exports import ensure_export_cleanup, new_export_path
from .sessions.telemetry import async_setup_session_history

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

SESSION_LOG_FILE = "growatt_thor_sessions.csv"

ATTR_CONFIG_ENTRY_ID = "config_entry_id"

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

    charge_point = coordinator.runtime_data.get("charge_point")
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
        coordinator.dashboard_sessions = await hass.async_add_executor_job(
            lambda: dashboard_session_data(
                path,
                source_instance_id=coordinator.source_instance_id,
                charge_point_id=coordinator.charge_point_id,
                include_unassigned_archive=coordinator.runtime_data.get(
                    "owns_legacy_history", False
                ),
            )
        )
        coordinator.async_set_updated_data(True)
    _LOGGER.debug("📝 Session appended to CSV: %s", path)


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
        coordinator.dashboard_sessions = await hass.async_add_executor_job(
            lambda: dashboard_session_data(
                path,
                source_instance_id=coordinator.source_instance_id,
                charge_point_id=coordinator.charge_point_id,
                include_unassigned_archive=coordinator.runtime_data.get(
                    "owns_legacy_history", False
                ),
            )
        )
        coordinator.async_set_updated_data(True)


def _register_services(hass: HomeAssistant) -> None:
    """Register domain services once for the lifetime of Home Assistant.

    The handlers resolve ``hass.data`` at call time.  They therefore remain
    well-defined while a config entry is being reloaded: exports can still use
    the historical CSV, while charger refresh reports a translated connection
    error instead of disappearing from the service registry.
    """
    if hass.services.has_service(DOMAIN, "refresh") and hass.services.has_service(
        DOMAIN, "export_sessions"
    ):
        return

    operations = IntegrationServiceOperations(hass.async_create_task)
    # Refreshes are single-flight per charger: concurrent calls for the same
    # entry share one physical read sequence, while different chargers never
    # wait for, or join, each other's refresh.
    refresh_operations: dict[str, IntegrationServiceOperations] = {}

    async def handle_refresh(call: ServiceCall):
        """Coalesce concurrent refresh calls and report incomplete reads.

        Without ``config_entry_id`` every loaded charger is refreshed.  The
        call succeeds when at least one charger was refreshed and none failed;
        a charger that is not connected is only logged.  With
        ``config_entry_id`` the named charger must be loaded and connected.
        """
        _LOGGER.debug("Manual refresh triggered")
        targets = loaded_entry_runtimes(hass.data.get(DOMAIN, {}))
        entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
        if entry_id is not None:
            # An unknown or unloaded entry has no reachable charger either.
            targets = [target for target in targets if target[0] == entry_id]

        refreshed = 0
        failure = None
        for target_entry_id, runtime_data in targets:
            entry_operations = refresh_operations.setdefault(
                target_entry_id,
                IntegrationServiceOperations(hass.async_create_task),
            )
            try:
                await entry_operations.async_refresh(runtime_data)
            except ChargerServiceUnavailable:
                _LOGGER.warning(
                    "No charge point connected for %s - cannot refresh",
                    target_entry_id,
                )
            except ManualRefreshFailed as exc:
                _LOGGER.warning(
                    "Manual refresh of %s failed during %s",
                    target_entry_id,
                    exc.step,
                )
                failure = failure or exc
            else:
                refreshed += 1

        if failure is not None:
            raise_communication_error(
                "refresh_failed",
                placeholders={"step": failure.step},
            )
        if not refreshed:
            raise_charger_disconnected()
        _LOGGER.info("Manual refresh completed successfully")

    async def handle_export_sessions(call: ServiceCall):
        """Export one date range without racing the same destination file."""
        date_from_str = call.data.get("date_from")
        date_to_str = call.data.get("date_to")

        try:
            date_from, date_to = parse_export_date_range(
                date_from_str,
                date_to_str,
            )
        except DateRangeValidationError as exc:
            if exc.reason == DateRangeValidationReason.REVERSED_RANGE:
                raise_action_validation("invalid_export_date_range")
            raise_action_validation("invalid_export_date")

        source_path = _get_session_log_path(hass)
        export_path = new_export_path(hass.config.path("www"))
        export_filename = export_path.name
        target_key = str(Path(export_path).resolve())

        async def _export_and_notify() -> int:
            def _export() -> int:
                return export_session_rows(
                    source_path,
                    export_path,
                    date_from=date_from,
                    date_to=date_to,
                    time_zone=installation_time_zone(hass),
                )

            ensure_export_cleanup(hass)
            count = await hass.async_add_executor_job(_export)
            pn_create(
                hass,
                (
                    f"Export ready: **{count} sessions** from "
                    f"{date_from_str} to {date_to_str}. Link expires in 15 minutes.\n\n"
                    f"[⬇️ Download CSV](/local/{export_filename})"
                ),
                title="Growatt THOR session export",
                notification_id=(f"growatt_thor_export_{date_from_str}_{date_to_str}"),
            )
            _LOGGER.info(
                "Session export: %d rows written to %s",
                count,
                export_path,
            )
            return count

        try:
            await operations.async_export(target_key, _export_and_notify)
        except Exception as exc:
            _LOGGER.error("Session export failed: %s", exc, exc_info=True)
            raise_communication_error("session_export_failed")

    if not hass.services.has_service(DOMAIN, "refresh"):
        hass.services.async_register(
            DOMAIN,
            "refresh",
            handle_refresh,
            schema=vol.Schema(
                {
                    vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
                }
            ),
        )
    if not hass.services.has_service(DOMAIN, "export_sessions"):
        hass.services.async_register(
            DOMAIN,
            "export_sessions",
            handle_export_sessions,
            schema=vol.Schema(
                {
                    vol.Required("date_from"): cv.string,
                    vol.Required("date_to"): cv.string,
                }
            ),
        )


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register integration-level services independently from config entries."""
    _register_services(hass)
    ensure_export_cleanup(hass)
    from .charging.pv_service import async_register_pv_linkage_service
    from .presentation.frontend import async_register_frontend
    from .sessions.websocket import async_register_session_websocket
    from .targets.services import async_register_target_services

    await async_register_frontend(hass)
    async_register_pv_linkage_service(hass)
    async_register_target_services(hass)
    async_register_session_websocket(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
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

        from .charging.authorization import CONF_AUTHORIZATION, LocalAuthorization

        coordinator = GrowattCoordinator(
            hass,
            source_instance_id=entry.entry_id,
            seed_from_legacy=await _legacy_seed_allowed(hass, entry),
        )
        coordinator.runtime_data = runtime_data
        coordinator.charge_point_id = entry.data.get("charge_point_id")

        def persist_charger_identity(cp_id):
            if entry.data.get("charge_point_id") != cp_id:
                hass.config_entries.async_update_entry(
                    entry, data={**entry.data, "charge_point_id": cp_id}
                )

        runtime_data["persist_charger_identity"] = persist_charger_identity
        runtime_data["owns_legacy_history"] = await _owns_legacy_history(hass, entry)
        coordinator.authorization = LocalAuthorization(entry.data.get(CONF_AUTHORIZATION))
        coordinator.battery_power_entity = entry.data.get(CONF_BATTERY_POWER_ENTITY)
        coordinator.battery_power_sign = entry.data.get(
            CONF_BATTERY_POWER_SIGN,
            BATTERY_POSITIVE_DISCHARGE,
        )
        coordinator.site_accounting_options = dict(entry.data)
        await coordinator.async_load_storage()
        runtime_data["coordinator"] = coordinator
        runtime_data["skip_polling_until"] = 0.0
        runtime_data["append_session_to_csv"] = lambda session: _append_session_to_csv(
            hass, coordinator, session
        )
        runtime_data["update_session_events_in_csv"] = lambda session_id, events: (
            _update_session_events_in_csv(hass, coordinator, session_id, events)
        )
        # Replay checkpointed completions before loading the dashboard summary.
        # Otherwise a restart could show history from before a recovered CSV append.
        await coordinator.sessions.async_flush_pending()
        session_log_path = _get_session_log_path(hass)

        def _load_retained_dashboard():
            enforce_session_retention(session_log_path)
            return dashboard_session_data(
                session_log_path,
                source_instance_id=entry.entry_id,
                charge_point_id=coordinator.charge_point_id,
                include_unassigned_archive=runtime_data.get("owns_legacy_history", False),
                time_zone=installation_time_zone(hass),
            )

        async def refresh_dashboard():
            coordinator.dashboard_sessions = await hass.async_add_executor_job(
                _load_retained_dashboard
            )
            coordinator.async_set_updated_data(True)

        runtime_data["refresh_dashboard"] = refresh_dashboard
        await refresh_dashboard()

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
        runtime_data["poll_interval"] = poll_interval
        poll_interval_schedule = PollIntervalSchedule(poll_interval)
        runtime_data["poll_interval_schedule"] = poll_interval_schedule

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
        runtime_data["server"] = server
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

    runtime_data["startup_check_task"] = startup_check_task

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

    async def periodic_external_meter_poll():
        """Poll the external meter while a charge point is connected."""
        loop = asyncio.get_event_loop()
        poll_started = False

        while True:
            # The schedule can be woken by the options flow.  This makes a new
            # interval effective for the very next cycle instead of leaving a
            # stale sleep (or requiring an integration reload).
            await poll_interval_schedule.async_wait_for_next_cycle()
            poll_interval = poll_interval_schedule.interval
            if not poll_started:
                _LOGGER.info(
                    "External meter poll started (interval: %ds)",
                    poll_interval,
                )
                poll_started = True
            try:
                skip_until = runtime_data.get("skip_polling_until", 0.0)
                current_time = loop.time()

                while current_time < skip_until:
                    if not getattr(
                        periodic_external_meter_poll,
                        "_skip_logged",
                        False,
                    ):
                        remaining = int(skip_until - current_time)
                        _LOGGER.info("⏸️ Polling paused (%ds remaining)", remaining)
                        periodic_external_meter_poll._skip_logged = True
                    await asyncio.sleep(min(1, skip_until - current_time))
                    current_time = loop.time()
                periodic_external_meter_poll._skip_logged = False

                charge_point = runtime_data.get("charge_point")
                coordinator = runtime_data.get("coordinator")

                if charge_point and coordinator:
                    _LOGGER.debug("Polling external meter (%ds interval)", poll_interval)
                    # Meter data is periodic and may be skipped once.  It must
                    # never queue behind or wake together with a configuration
                    # write, because the THOR firmware is sensitive to bursts
                    # of integration-initiated requests.
                    await charge_point.trigger_external_meterval(skip_if_writes_pending=True)
                else:
                    _LOGGER.debug("External meter poll skipped: charger not connected")

            except Exception as exc:
                _LOGGER.error("💥 Smart poll crashed: %s", exc, exc_info=True)

    runtime_data["polling_task"] = hass.async_create_background_task(
        periodic_external_meter_poll(),
        name=f"growatt_thor_external_meter_poll_{entry.entry_id}",
    )

    from .charging.pv_service import async_setup_pv_linkage_service
    from .energy.stop_runtime import EnergyStopGuard
    from .targets.services import async_setup_target_services

    await async_setup_pv_linkage_service(hass, entry, coordinator)
    await async_setup_target_services(hass, entry, coordinator)
    runtime_data["energy_stop_guard"] = EnergyStopGuard(hass, coordinator)
    runtime_data["energy_stop_guard"].refresh()
    runtime_data["session_history_unsub"] = async_setup_session_history(hass, coordinator)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
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

    startup_task = runtime_data.get("startup_check_task")
    if startup_task is not None:
        startup_task.cancel()
        with suppress(asyncio.CancelledError):
            await startup_task

    polling_task = runtime_data.get("polling_task")
    if polling_task:
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass

    energy_stop_guard = runtime_data.get("energy_stop_guard")
    if energy_stop_guard is not None:
        await energy_stop_guard.async_shutdown()

    if stop_history := runtime_data.get("session_history_unsub"):
        stop_history()

    coordinator = runtime_data.get("coordinator")
    if coordinator is not None:
        # The write queue may intentionally be waiting for a reconnect.  Stop
        # that wait before releasing the runtime so no background task
        # survives a reload of the integration.
        await coordinator.async_shutdown()

    server = runtime_data.get("server")
    if server:
        server.close()
        await server.wait_closed()

    from .charging.pv_service import async_unload_pv_linkage_service
    from .targets.services import async_unload_target_services

    async_unload_pv_linkage_service(hass, entry)
    async_unload_target_services(hass, entry)
    release_entry_runtime(domain_data, entry.entry_id, runtime_data)
    return True
