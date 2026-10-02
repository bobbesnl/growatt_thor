"""Read current HA tariff states without treating an unchanged price as stale."""
from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any

from .accounting import Tariff
from .currency import normalized_price_unit
from .observations import parse_at


def tariff_from_state(state: Any, currency: str) -> Tariff:
    """Honor availability and declared validity; state age is not price validity."""
    unknown = Tariff(None, currency=currency)
    if state is None:
        return unknown
    attributes = getattr(state, "attributes", {})
    if attributes.get("restored") or normalized_price_unit(
        attributes.get("unit_of_measurement"), currency
    ) is None:
        return unknown
    try:
        price = float(state.state)
    except (AttributeError, TypeError, ValueError):
        return unknown
    observed_at = parse_at(getattr(state, "last_updated", None))
    if not isfinite(price) or observed_at is None:
        return unknown

    # A current timeslot is more specific than an agreement spanning months.
    # Reject malformed declared bounds instead of silently accepting an old price.
    slot_keys = ("active_timeslot_from", "active_timeslot_to")
    slot = any(attributes.get(key) not in (None, "") for key in slot_keys)
    keys = slot_keys if slot else ("valid_from", "valid_to")
    bounds: list[datetime | None] = []
    for key in keys:
        value = attributes.get(key)
        parsed = parse_at(value) if value not in (None, "") else None
        if value not in (None, "") and parsed is None:
            return unknown
        bounds.append(parsed)
    start, end = bounds
    if start is not None and end is not None and end <= start:
        return unknown
    # HA leaves last_updated unchanged while a fixed or repeated tariff is valid.
    # Retain its lower time bound so a new price cannot rewrite earlier EV deltas.
    return Tariff(
        price, currency=currency, observed_at=observed_at,
        max_age_s=None, valid_from=start, valid_to=end,
    )
