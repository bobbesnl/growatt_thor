"""UTC instants at application boundaries; explicit zones for device wall clocks."""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def parse_utc(
    value: object,
    *,
    allow_datetime: bool = True,
    allow_naive: bool = False,
    normalize: bool = True,
    strip: bool = False,
    minimum_length: int = 0,
) -> datetime | None:
    """Parse an ISO instant; explicit options retain legacy parser boundaries.

    Naive values remain naive when allowed, so callers retain their established
    local-calendar or host-local timestamp behavior instead of guessing UTC.
    """
    if isinstance(value, datetime) and allow_datetime:
        parsed = value
    elif isinstance(value, str) and len(value) >= minimum_length:
        try:
            text = value.strip() if strip else value
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed if allow_naive else None
    return parsed.astimezone(UTC) if normalize else parsed


def utc_instant(value: object, time_zone: str | tzinfo | None = None) -> datetime | None:
    """Resolve an explicit instant or an unambiguous time in the supplied zone."""
    parsed = parse_utc(
        value,
        allow_datetime=False,
        allow_naive=True,
        normalize=False,
        strip=True,
        minimum_length=16,
    )
    if parsed is None:
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


def installation_time_zone(hass, fallback="UTC", *, preserve_empty: bool = False):
    """Read HA's zone while preserving callers that distinguish empty settings."""
    value = getattr(getattr(hass, "config", None), "time_zone", fallback)
    return value if preserve_empty else value or fallback
