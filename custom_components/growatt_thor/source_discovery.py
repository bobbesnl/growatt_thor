"""Source-sensor discovery for Home Assistant options forms."""

from .energy.currency import normalized_price_unit
from .energy.sources import is_power_sensor, state_attributes

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


def _candidate_score(entity_id: str, state, role: str = "battery") -> int:
    name = str(state_attributes(state).get("friendly_name") or "")
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
        score += sum(weight for term, weight in _BIDIRECTIONAL_TERMS.items() if term in text)
    return score


def _state_map(states) -> dict:
    """Normalize HA's StateMachine and mapping-shaped test doubles."""
    async_all = getattr(states, "async_all", None)
    if callable(async_all):
        return {
            state.entity_id: state for state in async_all() if getattr(state, "entity_id", None)
        }
    items = getattr(states, "items", None)
    return dict(items()) if callable(items) else {}


def power_sensor_options(
    states,
    configured_entity: str | None = None,
    *,
    role: str = "battery",
    exclude: set[str] | None = None,
) -> list[dict]:
    """Rank likely sources without inferring their physical role from a name."""
    state_map = _state_map(states)
    candidates = []
    for entity_id, state in state_map.items():
        if entity_id in (exclude or set()) and entity_id != configured_entity:
            continue
        if not is_power_sensor(entity_id, state) and entity_id != configured_entity:
            continue
        attributes = state_attributes(state)
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


def tariff_sensor_options(
    states, currency: str, configured_entity: str | None = None
) -> list[dict]:
    """Offer compatible prices, retaining an old selection so it can be repaired."""

    candidates = []
    for entity_id, state in _state_map(states).items():
        attrs = state_attributes(state)
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
