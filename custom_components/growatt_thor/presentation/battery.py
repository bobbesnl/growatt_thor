"""Battery-flow attributes exposed by the dashboard projection."""

from datetime import datetime
from typing import TypedDict

from ..energy.sources import (
    BATTERY_POSITIVE_CHARGE,
    power_w,
    state_attributes,
)
from .contracts import BatteryOwner


def _timestamp(value: object) -> str | None:
    if isinstance(value, datetime):
        value = value.isoformat()
    if not isinstance(value, str) or not value:
        return None
    return value.replace("+00:00", "Z")


class BatteryFlowData(TypedDict, total=False):
    battery_w: float | None
    battery_received_at: str | None
    battery_sign: str


def battery_power_attributes(coordinator: BatteryOwner) -> BatteryFlowData:
    """Return a normalized optional battery-flow observation for the card."""
    entity_id = coordinator.battery_power_entity
    if not entity_id:
        return {}
    hass = coordinator.hass
    state = getattr(hass, "states", {}).get(entity_id) if hass else None
    value = None if state_attributes(state).get("restored") else power_w(state)
    if value is not None and coordinator.battery_power_sign == BATTERY_POSITIVE_CHARGE:
        value = -value
    return {
        "battery_w": value,
        "battery_received_at": _timestamp(
            getattr(state, "last_reported", None) or getattr(state, "last_updated", None)
        ),
        "battery_sign": "positive_discharge",
    }
