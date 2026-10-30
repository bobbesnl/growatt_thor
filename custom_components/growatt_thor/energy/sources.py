"""Unit and sign normalization for optional Home Assistant power sources."""

from __future__ import annotations

from math import isfinite

from .options import CONF_BATTERY_POWER_ENTITY as CONF_BATTERY_POWER_ENTITY
from .options import CONF_BATTERY_POWER_SIGN as CONF_BATTERY_POWER_SIGN

BATTERY_POSITIVE_DISCHARGE = "positive_discharge"
BATTERY_POSITIVE_CHARGE = "positive_charge"
BATTERY_POWER_SIGNS = (BATTERY_POSITIVE_DISCHARGE, BATTERY_POSITIVE_CHARGE)

POWER_UNIT_FACTORS = {
    "W": 1.0,
    "kW": 1_000.0,
    "MW": 1_000_000.0,
}


def state_attributes(state) -> dict:
    attributes = getattr(state, "attributes", None)
    return attributes if isinstance(attributes, dict) else {}


def is_power_sensor(entity_id: str, state) -> bool:
    """Return whether an entity is a sensor with a supported power unit."""
    return (
        entity_id.startswith("sensor.")
        and state_attributes(state).get("unit_of_measurement") in POWER_UNIT_FACTORS
    )


def power_w(state) -> float | None:
    """Normalize a supported HA power state to watts."""
    if state is None:
        return None
    factor = POWER_UNIT_FACTORS.get(state_attributes(state).get("unit_of_measurement"))
    if factor is None:
        return None
    try:
        value = float(getattr(state, "state", None)) * factor
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) else None


def duplicate_source_fields(assignments: dict[str, str | None]) -> set[str]:
    """Independent power flows cannot share the same entity."""
    selected = [entity for entity in assignments.values() if entity]
    return {field for field, entity in assignments.items() if entity and selected.count(entity) > 1}
