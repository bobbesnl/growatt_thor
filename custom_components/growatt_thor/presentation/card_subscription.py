"""Card data over a WebSocket subscription instead of a large state attribute.

The payload is the same ``thor_card`` contract the status sensor still exposes
as an attribute, so the card can fall back to the attribute while an older
browser bundle or a failed subscription is in play.

A subscriber receives ``{"type": "data", "data": ...}`` once after subscribing
and again whenever the payload changes; unchanged coordinator updates are not
sent. When the entry unloads, the subscriber receives ``{"type": "unloaded"}``
and the subscription ends; the card subscribes again after a reload.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypedDict, cast

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from ..const import DOMAIN
from ..runtime.keys import CARD_SUBSCRIPTIONS, COORDINATOR
from ..runtime.ownership import entry_runtime_data
from .entity_map import card_payload

if TYPE_CHECKING:
    from ..coordinator import GrowattCoordinator


class CardSubscribeMessage(TypedDict):
    id: int
    type: str
    entry_id: str


type CardSubscribeHandler = Callable[
    [HomeAssistant, websocket_api.ActiveConnection, CardSubscribeMessage], None
]
# HA owns validation; this adapter retains the handler signature for mypy.
_websocket_command = cast(
    Callable[[dict[Any, Any]], Callable[[CardSubscribeHandler], CardSubscribeHandler]],
    websocket_api.websocket_command,
)


@_websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/card/subscribe",
        vol.Required("entry_id"): cv.string,
    }
)
@callback
def websocket_card_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: CardSubscribeMessage,
) -> None:
    runtime = entry_runtime_data(hass.data.get(DOMAIN, {}), msg["entry_id"])
    coordinator = cast("GrowattCoordinator | None", runtime.get(COORDINATOR) if runtime else None)
    subscriptions = cast(
        "set[Callable[[], None]] | None", runtime.get(CARD_SUBSCRIPTIONS) if runtime else None
    )
    if coordinator is None or subscriptions is None:
        connection.send_error(msg["id"], "not_found", "Config entry not loaded")
        return

    last_sent: str | None = None

    @callback
    def send_update() -> None:
        nonlocal last_sent
        payload = card_payload(hass, coordinator)
        encoded = json.dumps(payload, sort_keys=True, default=str)
        if encoded == last_sent:
            return
        last_sent = encoded
        connection.send_message(
            websocket_api.event_message(msg["id"], {"type": "data", "data": payload})
        )

    remove_listener: Callable[[], None] | None = coordinator.async_add_listener(send_update)

    @callback
    def close() -> None:
        # Runs twice after an unload: once from ``end`` and again when HA
        # drops the connection's subscriptions. Older coordinators raise on a
        # second listener removal.
        nonlocal remove_listener
        if remove_listener is not None:
            remove_listener()
            remove_listener = None
        subscriptions.discard(end)

    @callback
    def end() -> None:
        # Entry unload: tell the card to fall back and subscribe again later.
        close()
        connection.send_message(websocket_api.event_message(msg["id"], {"type": "unloaded"}))

    subscriptions.add(end)
    # HA calls this when the client unsubscribes or the connection closes.
    connection.subscriptions[msg["id"]] = close
    connection.send_result(msg["id"])
    send_update()


def async_register_card_websocket(hass: HomeAssistant) -> None:
    """Register the card subscription once during integration setup."""
    websocket_api.async_register_command(hass, websocket_card_subscribe)


def end_card_subscriptions(subscriptions: set[Callable[[], None]] | None) -> None:
    """Notify and end every card subscription of an unloading entry."""
    for end in list(subscriptions or ()):
        end()
