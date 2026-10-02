"""Authenticated on-demand session details for the bundled Lovelace card."""
from __future__ import annotations

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from ..const import DOMAIN
from .csv import session_detail_data


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/session_detail",
        vol.Required("entry_id"): cv.string,
        vol.Required("session_id"): cv.string,
    }
)
@websocket_api.async_response
async def websocket_session_detail(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Return one bounded retained session to an authenticated frontend."""
    runtime = hass.data.get(DOMAIN, {})
    if runtime.get("config_entry_id") != msg["entry_id"]:
        connection.send_error(msg["id"], "not_found", "Config entry not found")
        return

    detail = await hass.async_add_executor_job(
        session_detail_data,
        hass.config.path("growatt_thor_sessions.csv"),
        msg["session_id"],
    )
    if detail is None:
        connection.send_error(msg["id"], "not_found", "Session not found")
        return
    connection.send_result(msg["id"], {"schema": 1, "item": detail})


def async_register_session_websocket(hass: HomeAssistant) -> None:
    """Register the session-detail command once during integration setup."""
    websocket_api.async_register_command(hass, websocket_session_detail)
