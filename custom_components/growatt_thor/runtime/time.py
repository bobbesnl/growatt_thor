"""UTC instants at application boundaries; explicit zones for device wall clocks."""

from __future__ import annotations

from datetime import UTC, datetime, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def utc_instant(value: object, time_zone: str | tzinfo | None = None) -> datetime | None:
    """Resolve an explicit instant or an unambiguous time in the supplied zone."""
    if not isinstance(value, str) or len(value) < 16:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC)
    if not time_zone:
        return None
    try:
        zone = time_zone if isinstance(time_zone, tzinfo) else ZoneInfo(time_zone)
    except (ValueError, ZoneInfoNotFoundError):
        return None
    candidates = set()
    for fold in (0, 1):
        utc = parsed.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        if utc.astimezone(zone).replace(tzinfo=None) == parsed:
            candidates.add(utc)
    return candidates.pop() if len(candidates) == 1 else None


def utc_timestamp(value: object, time_zone: str | tzinfo | None = None) -> str | None:
    parsed = utc_instant(value, time_zone)
    return parsed.isoformat().replace("+00:00", "Z") if parsed is not None else None


def installation_time_zone(hass) -> str:
    return getattr(getattr(hass, "config", None), "time_zone", None) or "UTC"
