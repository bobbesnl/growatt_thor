"""Shared session CSV row shapes, normalization and header order."""

from __future__ import annotations

import json
from datetime import date
from math import isfinite
from typing import Any

from ..timestamps import parse_utc
from .events import normalize_session_events
from .identity import (
    SOURCE_LEGACY_UNKNOWN,
    build_session_id,
)
from .series import SESSION_CURVE_POINT_LIMIT, downsample_curve
from .telemetry import CONTEXT_CURVES

SESSION_RETENTION_DAYS = 365


SESSION_RETENTION_ROWS = 1000


SESSION_LOG_HEADERS = [
    "timestamp",
    "charger_id",
    "source_instance_id",
    "location",
    "start_time",
    "end_time",
    "energy_kwh",
    "cost",
    "duration_minutes",
    "transaction_id",
    "session_id",
    "session_source",
    "effective_charging_minutes",
    "authorized_identifier",
    "authorized_alias",
    "green_energy_kwh",
    "power_curve",
    *CONTEXT_CURVES,
    "site_house_load_source",
    "events",
    "source_energy_kwh",
    "effective_grid_cost",
    "accounting_coverage",
    "accounting_quality",
    "accounting_policy",
]


SESSION_EXPORT_HEADERS = [
    "charger_id",
    "source_instance_id",
    "location",
    "start_time",
    "end_time",
    "energy_kwh",
    "cost",
    "duration_minutes",
    "transaction_id",
    "session_id",
    "session_source",
    "effective_charging_minutes",
    "authorized_identifier",
    "authorized_alias",
    "green_energy_kwh",
    "source_energy_kwh",
    "effective_grid_cost",
    "accounting_coverage",
    "accounting_quality",
    "accounting_policy",
]


def csv_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def accounting_json(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def accounting_sources(value: Any) -> dict | None:
    decoded = accounting_json(value)
    keys = ("direct_solar", "direct_grid", "battery_unknown", "unknown")
    if not decoded or any(
        csv_float(decoded.get(key)) is None
        or not isfinite(float(decoded[key]))
        or float(decoded[key]) < 0
        for key in keys
    ):
        return None
    return {key: float(decoded[key]) for key in keys}


def accounting_policy(value: Any) -> dict | None:
    decoded = accounting_json(value)
    if (
        decoded.get("id") not in ("grid_first", "load_first", "mixed")
        or decoded.get("version") != 1
    ):
        return None
    policy = {"id": decoded["id"], "version": 1}
    if decoded.get("topology") in ("grid_only", "pv", "pv_battery"):
        policy["topology"] = decoded["topology"]
    return policy


def normalize_session_row(row: dict[str, Any]) -> dict[str, Any]:
    """Add an explicit legacy identity when a historical row has none."""
    normalized = dict(row)
    if normalized.get("session_id") and normalized.get("session_source"):
        return normalized

    normalized["session_source"] = SOURCE_LEGACY_UNKNOWN
    normalized["session_id"] = build_session_id(
        source=SOURCE_LEGACY_UNKNOWN,
        charge_point_id=normalized.get("charger_id"),
        transaction_id=normalized.get("transaction_id"),
        started_at=normalized.get("start_time"),
        ended_at=normalized.get("end_time"),
    )
    return normalized


def target_headers(existing_headers: list[str] | None) -> list[str]:
    headers = list(existing_headers or ())
    for header in SESSION_LOG_HEADERS:
        if header not in headers:
            headers.append(header)
    return headers


def session_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = parse_utc(
            value, allow_datetime=False, allow_naive=True, normalize=False, strip=True
        )
        return parsed.date() if parsed is not None else None
    except ValueError:
        return None


def power_curve(
    value: Any,
    *,
    event_times: Any = (),
) -> list[list[Any]]:
    """Decode bounded [timestamp, watts] pairs without inventing samples."""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        decoded = value
    else:
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
    return downsample_curve(
        decoded,
        limit=SESSION_CURVE_POINT_LIMIT,
        event_times=event_times,
    )


def session_events(value: Any) -> list[dict[str, str]]:
    """Decode the bounded event contract without exposing arbitrary JSON."""
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return normalize_session_events(decoded)
