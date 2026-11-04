"""Dashboard control IDs from the entry's registry and the assembled card payload."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers import entity_registry as er

from ..const import DOMAIN
from .card_data import dashboard_attributes

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..coordinator import GrowattCoordinator


def dashboard_entity_map(hass: HomeAssistant, entry_id: str | None) -> dict[str, str]:
    prefix = f"{entry_id}_"
    wanted = {
        "start_charging",
        "stop_charging",
        "max_current",
        "working_mode_control",
        "authorization_mode_control",
        "last_charger_fault",
        "last_session_energy",
        "last_session_duration",
        "last_session_cost",
    }
    return {
        item.unique_id[len(prefix) :]: item.entity_id
        for item in er.async_entries_for_config_entry(er.async_get(hass), entry_id)
        if item.platform == DOMAIN
        and item.unique_id.startswith(prefix)
        and item.unique_id[len(prefix) :] in wanted
        and not item.disabled_by
    }


def card_payload(hass: HomeAssistant, coordinator: GrowattCoordinator) -> dict[str, Any]:
    """Build the card contract shared by the attribute and the subscription."""
    data = dashboard_attributes(coordinator)
    data["entities"] = dashboard_entity_map(hass, coordinator.source_instance_id)
    return data
