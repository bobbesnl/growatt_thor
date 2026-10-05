"""Read current HA tariff states without treating an unchanged price as stale."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .accounting import Tariff
from .currency import normalized_price_unit
from .observations import parse_at


def _daily_bounds(start: object, end: object, at: datetime | None,
                  time_zone: str) -> tuple[datetime, datetime] | None:
    """Resolve time-only slots in HA's local day, including slots crossing midnight."""
    if not isinstance(start, str) or not isinstance(end, str) or at is None or at.tzinfo is None:
        return None
    try:
        start_time, end_time = time.fromisoformat(start), time.fromisoformat(end)
        zone = ZoneInfo(time_zone)
    except (ValueError, ZoneInfoNotFoundError):
        return None
    if start_time.tzinfo is not None or end_time.tzinfo is not None or start_time == end_time:
        return None
    local = at.astimezone(zone)
    day = local.date()
    overnight = end_time < start_time
    if overnight and local.time() < end_time:
        day -= timedelta(days=1)
    return (datetime.combine(day, start_time, zone),
            datetime.combine(day + timedelta(days=int(overnight)), end_time, zone))


def tariff_from_state(state: Any, currency: str, *, at: datetime | None = None,
                      time_zone: str = "UTC") -> Tariff:
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
    # Some tariff integrations expose a daily schedule (e.g. 05:00–00:00),
    # rather than dated slots. Anchor it to the sample's local day, not UTC.
    daily = _daily_bounds(*(attributes.get(key) for key in slot_keys), at, time_zone) if slot else None
    bounds: list[datetime | None] = []
    if daily is not None:
        start, end = daily
        for key in ("valid_from", "valid_to"):
            value = attributes.get(key)
            bound = parse_at(value) if value not in (None, "") else None
            if value not in (None, "") and bound is None:
                return unknown
            if bound is not None:
                if key == "valid_from":
                    start = max(start, bound)
                else:
                    end = min(end, bound)
        bounds = [start, end]
    else:
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
