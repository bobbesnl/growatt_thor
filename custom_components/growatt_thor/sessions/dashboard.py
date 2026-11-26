"""Refresh retained dashboard history after setup or a history write."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from ..runtime.keys import OWNS_LEGACY_HISTORY
from .contracts import DashboardHistoryOwner
from .csv import enforce_session_retention
from .history_views import dashboard_session_data

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


class HistoryDisplayOptions(TypedDict, total=False):
    time_zone: str


async def async_refresh_dashboard(
    hass: HomeAssistant,
    coordinator: DashboardHistoryOwner,
    path: str | Path,
    *,
    retain: bool = False,
    time_zone: str | None = None,
) -> None:
    def load() -> dict[str, Any]:
        if retain:
            enforce_session_retention(path)
        options: HistoryDisplayOptions = {"time_zone": time_zone} if time_zone is not None else {}
        return dashboard_session_data(
            path,
            source_instance_id=coordinator.source_instance_id,
            charge_point_id=coordinator.charge_point_id,
            include_unassigned_archive=coordinator.runtime_data.get(OWNS_LEGACY_HISTORY, False),
            **options,
        )

    coordinator.dashboard_sessions = await hass.async_add_executor_job(load)
    coordinator.async_set_updated_data(True)
