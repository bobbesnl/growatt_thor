"""Battery-flow attributes exposed by the dashboard projection."""

from datetime import datetime

from ..energy.sources import (
    BATTERY_POSITIVE_CHARGE,
    BATTERY_POSITIVE_DISCHARGE,
    power_w,
    state_attributes,
)


def _timestamp(value) -> str | None:
    if isinstance(value, datetime):
        value = value.isoformat()
    if not isinstance(value, str) or not value:
        return None
    return value.replace("+00:00", "Z")


def battery_power_attributes(coordinator) -> dict:
    """Return a normalized optional battery-flow observation for the card."""
    entity_id = getattr(coordinator, "battery_power_entity", None)
    if not entity_id:
        return {}
    hass = getattr(coordinator, "hass", None)
    state = getattr(hass, "states", {}).get(entity_id) if hass else None
    value = None if state_attributes(state).get("restored") else power_w(state)
    if (
        value is not None
        and getattr(coordinator, "battery_power_sign", BATTERY_POSITIVE_DISCHARGE)
        == BATTERY_POSITIVE_CHARGE
    ):
        value = -value
    return {
        "battery_w": value,
        "battery_received_at": _timestamp(
            getattr(state, "last_reported", None) or getattr(state, "last_updated", None)
        ),
        "battery_sign": "positive_discharge",
    }
