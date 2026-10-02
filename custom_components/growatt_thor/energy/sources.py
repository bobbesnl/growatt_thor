"""Optional Home Assistant power sources used by the dashboard contract."""
from __future__ import annotations

from datetime import datetime
from math import isfinite

CONF_BATTERY_POWER_ENTITY = "battery_power_entity"
CONF_BATTERY_POWER_SIGN = "battery_power_sign"

BATTERY_POSITIVE_DISCHARGE = "positive_discharge"
BATTERY_POSITIVE_CHARGE = "positive_charge"
BATTERY_POWER_SIGNS = (BATTERY_POSITIVE_DISCHARGE, BATTERY_POSITIVE_CHARGE)

POWER_UNIT_FACTORS = {
    "W": 1.0,
    "kW": 1_000.0,
    "MW": 1_000_000.0,
}

_BATTERY_TERMS = {
    "battery": 100,
    "batterie": 100,
    "akku": 90,
    "storage": 80,
    "speicher": 80,
    "bms": 60,
}
_BIDIRECTIONAL_TERMS = {
    "combined": 50,
    "bidirectional": 50,
    "net power": 40,
    "power flow": 40,
    "leistungsfluss": 40,
}


def _attributes(state) -> dict:
    attributes = getattr(state, "attributes", None)
    return attributes if isinstance(attributes, dict) else {}


def is_power_sensor(entity_id: str, state) -> bool:
    """Return whether an entity is a sensor with a supported power unit."""
    return (
        entity_id.startswith("sensor.")
        and _attributes(state).get("unit_of_measurement") in POWER_UNIT_FACTORS
    )


def _candidate_score(entity_id: str, state, role: str = "battery") -> int:
    name = str(_attributes(state).get("friendly_name") or "")
    text = f"{name} {entity_id}".casefold()
    if role != "battery":
        terms = {
            "solar": ("solar", "pv", "photovolta", "generation", "erzeugung"),
            "grid": ("grid", "netz", "import", "export"),
            "household": ("house", "home", "load", "haus", "verbrauch"),
        }.get(role, ())
        return sum(50 for term in terms if term in text)
    score = sum(weight for term, weight in _BATTERY_TERMS.items() if term in text)
    if score:
        score += sum(
            weight for term, weight in _BIDIRECTIONAL_TERMS.items() if term in text
        )
    return score


def _state_map(states) -> dict:
    """Normalize HA's StateMachine and mapping-shaped test doubles."""
    async_all = getattr(states, "async_all", None)
    if callable(async_all):
        return {
            state.entity_id: state
            for state in async_all()
            if getattr(state, "entity_id", None)
        }
    items = getattr(states, "items", None)
    return dict(items()) if callable(items) else {}


def power_sensor_options(states, configured_entity: str | None = None, *,
                         role: str = "battery", exclude: set[str] | None = None) -> list[dict]:
    """Rank likely sources without inferring their physical role from a name."""
    state_map = _state_map(states)
    candidates = []
    for entity_id, state in state_map.items():
        if entity_id in (exclude or set()) and entity_id != configured_entity:
            continue
        if not is_power_sensor(entity_id, state) and entity_id != configured_entity:
            continue
        attributes = _attributes(state)
        name = str(attributes.get("friendly_name") or entity_id)
        unit = attributes.get("unit_of_measurement")
        unit_label = f" · {unit}" if unit else ""
        candidates.append(
            (
                _candidate_score(entity_id, state, role),
                name.casefold(),
                entity_id,
                {"value": entity_id, "label": f"{name}{unit_label} · {entity_id}"},
            )
        )

    if configured_entity and configured_entity not in state_map:
        candidates.append(
            (
                _candidate_score(configured_entity, None, role),
                configured_entity.casefold(),
                configured_entity,
                {"value": configured_entity, "label": configured_entity},
            )
        )

    candidates.sort(key=lambda candidate: (-candidate[0], candidate[1], candidate[2]))
    return [{"value": "", "label": "—"}, *(candidate[3] for candidate in candidates)]


def power_w(state) -> float | None:
    """Normalize a supported HA power state to watts."""
    if state is None:
        return None
    factor = POWER_UNIT_FACTORS.get(_attributes(state).get("unit_of_measurement"))
    if factor is None:
        return None
    try:
        value = float(getattr(state, "state", None)) * factor
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) else None


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
    value = power_w(state)
    if (
        value is not None
        and getattr(coordinator, "battery_power_sign", BATTERY_POSITIVE_DISCHARGE)
        == BATTERY_POSITIVE_CHARGE
    ):
        value = -value
    return {
        "battery_w": value,
        "battery_received_at": _timestamp(getattr(state, "last_updated", None)),
        "battery_sign": "positive_discharge",
    }


def duplicate_source_fields(assignments: dict[str, str | None]) -> set[str]:
    """Independent power flows cannot share the same entity."""
    selected = [entity for entity in assignments.values() if entity]
    return {field for field, entity in assignments.items() if entity and selected.count(entity) > 1}


def tariff_sensor_options(states, currency: str, configured_entity: str | None = None) -> list[dict]:
    """Offer compatible prices, retaining an old selection so it can be repaired."""
    from .currency import normalized_price_unit

    candidates = []
    for entity_id, state in _state_map(states).items():
        attrs = _attributes(state)
        unit = attrs.get("unit_of_measurement")
        if entity_id != configured_entity and (
            not entity_id.startswith("sensor.") or normalized_price_unit(unit, currency) is None
        ):
            continue
        name = attrs.get("friendly_name") or entity_id
        candidates.append({"value": entity_id, "label": f"{name} · {unit or '—'} · {entity_id}"})
    if configured_entity and not any(item["value"] == configured_entity for item in candidates):
        candidates.append({"value": configured_entity, "label": configured_entity})
    return sorted(candidates, key=lambda item: item["label"].casefold())
