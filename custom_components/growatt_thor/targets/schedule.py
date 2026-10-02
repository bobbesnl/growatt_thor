"""Timezone-safe helpers for one-time and daily charging schedules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_SCHEDULE_AHEAD = timedelta(days=30)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_start_at(value: object, *, now: datetime | None = None) -> datetime:
    """Return a future UTC datetime from an explicit timezone-aware value."""
    if not isinstance(value, str):
        raise ValueError("start_at_must_be_iso_datetime")  # noqa: TRY004
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        start = datetime.fromisoformat(normalized)
    except ValueError:
        raise ValueError("start_at_must_be_iso_datetime") from None
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("start_at_timezone_required")
    start = start.astimezone(timezone.utc)
    current = (now or utc_now()).astimezone(timezone.utc)
    if start <= current:
        raise ValueError("start_at_must_be_future")
    if start - current > MAX_SCHEDULE_AHEAD:
        raise ValueError("start_at_too_far")
    return start


def stored_start_at(value: object) -> datetime | None:
    """Parse a retained UTC timestamp without asserting that it is future."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        start = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if start.tzinfo is None or start.utcoffset() is None:
        return None
    return start.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def reservation_expiry(value: datetime, time_zone: str) -> str:
    """Encode Growatt's captured timezone-naive local ReserveNow boundary."""
    try:
        local = value.astimezone(ZoneInfo(time_zone))
    except ZoneInfoNotFoundError as exc:
        raise ValueError("invalid_time_zone") from exc
    return local.strftime("%Y-%m-%dT%H:%M:%S.000")


def next_daily_start(
    previous: datetime,
    *,
    now: datetime,
    time_zone: str,
) -> datetime:
    """Return the next future occurrence of a local wall-clock time."""
    try:
        zone = ZoneInfo(time_zone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("invalid_time_zone") from exc
    local_previous = previous.astimezone(zone)
    local_now = now.astimezone(zone)
    candidate = datetime.combine(
        local_now.date(),
        local_previous.timetz().replace(tzinfo=None),
        tzinfo=zone,
    )
    while candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)
