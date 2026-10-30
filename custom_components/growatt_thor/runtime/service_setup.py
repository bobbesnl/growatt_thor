"""Home Assistant registration for services that outlive individual entries."""

from __future__ import annotations

import logging
from pathlib import Path

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.persistent_notification import async_create as pn_create
from homeassistant.core import HomeAssistant, ServiceCall

from ..configuration.validation import (
    DateRangeValidationError,
    DateRangeValidationReason,
    parse_export_date_range,
)
from ..const import DOMAIN, SESSION_LOG_FILE
from ..sessions.exports import ensure_export_cleanup, export_session_rows, new_export_path
from ..timestamps import installation_time_zone
from .action_errors import (
    raise_action_validation,
    raise_charger_disconnected,
    raise_communication_error,
)
from .ownership import loaded_entry_runtimes
from .services import ChargerServiceUnavailable, IntegrationServiceOperations, ManualRefreshFailed

_LOGGER = logging.getLogger(__name__)
ATTR_CONFIG_ENTRY_ID = "config_entry_id"


def async_register_services(hass: HomeAssistant) -> None:
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

        source_path = hass.config.path(SESSION_LOG_FILE)
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
