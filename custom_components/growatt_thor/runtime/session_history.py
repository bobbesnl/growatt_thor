"""Attach Home Assistant events to the entry's session telemetry owner."""

from datetime import timedelta

from ..energy.options import CONF_GRID_ENTITY, CONF_HOUSE_ENTITY, CONF_SOLAR_ENTITY

SESSION_HISTORY_CAPTURE_INTERVAL_SECONDS = 30


def async_setup_session_history(hass, coordinator):
    """Observe configured HA sources immediately and snapshot pauses every 30s."""
    from homeassistant.helpers.event import async_track_time_interval

    async def capture(_event):
        coordinator.sessions.observe_context()

    async def state_changed(event):
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
        unsubscribe()
        raise

    def stop():
        unsubscribe()
        cancel_timer()

    return stop
