"""Authenticated on-demand session details for the bundled Lovelace card."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any, TypedDict, cast

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ..const import DOMAIN
from ..runtime.keys import COORDINATOR
from ..runtime.ownership import entry_runtime_data
from ..timestamps import installation_time_zone
from .contracts import DashboardHistoryOwner
from .history_views import session_detail_data


class SessionDetailMessage(TypedDict):
    id: int
    type: str
    entry_id: str
    session_id: str


type SessionDetailHandler = Callable[
    [HomeAssistant, websocket_api.ActiveConnection, SessionDetailMessage], Awaitable[None]
]
# HA owns validation and response scheduling; these adapters retain the handler signature.
_websocket_command = cast(
    Callable[[dict[Any, Any]], Callable[[SessionDetailHandler], SessionDetailHandler]],
    websocket_api.websocket_command,
)
_async_response = cast(
    Callable[[SessionDetailHandler], SessionDetailHandler], websocket_api.async_response
)


@_websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/session_detail",
        vol.Required("entry_id"): cv.string,
        vol.Required("session_id"): cv.string,
    }
)
@_async_response
async def websocket_session_detail(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: SessionDetailMessage,
) -> None:
    """Return one bounded retained session to an authenticated frontend."""
    runtime = entry_runtime_data(hass.data.get(DOMAIN, {}), msg["entry_id"])
    if runtime is None:
        connection.send_error(msg["id"], "not_found", "Config entry not found")
        return

    detail = await hass.async_add_executor_job(
        partial(
            session_detail_data,
            source_instance_id=msg["entry_id"],
            time_zone=installation_time_zone(hass),
            charge_point_id=cast(DashboardHistoryOwner, runtime[COORDINATOR]).charge_point_id,
        ),
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
