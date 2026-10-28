"""Dashboard control IDs selected from the owning config entry's registry."""

from homeassistant.helpers import entity_registry as er

from ..const import DOMAIN


def dashboard_entity_map(hass, entry_id) -> dict[str, str]:
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
