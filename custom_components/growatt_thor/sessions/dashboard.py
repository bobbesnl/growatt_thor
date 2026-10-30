"""Refresh retained dashboard history after setup or a history write."""

from ..runtime.keys import OWNS_LEGACY_HISTORY
from .csv import dashboard_session_data, enforce_session_retention


async def async_refresh_dashboard(hass, coordinator, path, *, retain=False, time_zone=None) -> None:
    def load():
        if retain:
            enforce_session_retention(path)
        options = {"time_zone": time_zone} if time_zone is not None else {}
        return dashboard_session_data(
            path,
            source_instance_id=coordinator.source_instance_id,
            charge_point_id=coordinator.charge_point_id,
            include_unassigned_archive=coordinator.runtime_data.get(OWNS_LEGACY_HISTORY, False),
            **options,
        )

    coordinator.dashboard_sessions = await hass.async_add_executor_job(load)
    coordinator.async_set_updated_data(True)
