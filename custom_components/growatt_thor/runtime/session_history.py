"""Attach Home Assistant events to the entry's session telemetry owner."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import Event, HomeAssistant

    from ..coordinator import GrowattCoordinator

from ..energy.options import CONF_GRID_ENTITY, CONF_HOUSE_ENTITY, CONF_SOLAR_ENTITY

SESSION_HISTORY_CAPTURE_INTERVAL_SECONDS = 30


def async_setup_session_history(
    hass: HomeAssistant, coordinator: GrowattCoordinator
) -> Callable[[], None]:
    """Observe configured HA sources immediately and snapshot pauses every 30s."""
    from homeassistant.helpers.event import async_track_time_interval

    async def capture(_event: object) -> None:
        coordinator.sessions.observe_context()

    async def state_changed(event: Event) -> None:
        options = coordinator.site_accounting_options
        sources = {
            options.get(key)
            for key in (
                CONF_SOLAR_ENTITY,
                CONF_HOUSE_ENTITY,
                CONF_GRID_ENTITY,
            )
        }
        sources.add(coordinator.battery_power_entity)
        sources.discard(None)
        if event.data.get("entity_id") in sources:
            coordinator.sessions.observe_context()

    unsubscribe = hass.bus.async_listen("state_changed", state_changed)
    try:
        cancel_timer = async_track_time_interval(
            hass, capture, timedelta(seconds=SESSION_HISTORY_CAPTURE_INTERVAL_SECONDS)
        )
    except BaseException:
        # Remove the listener if timer setup fails, including interruption, then propagate.
        unsubscribe()
        raise

    def stop() -> None:
        unsubscribe()
        cancel_timer()

    return stop
