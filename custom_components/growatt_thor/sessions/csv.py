"""Backward-compatible charging session CSV helpers."""
from __future__ import annotations

import csv
from functools import wraps
from threading import RLock
from datetime import date, datetime, timedelta
import json
from math import isfinite
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

from .identity import (
    SOURCE_LEGACY_UNKNOWN,
    build_session_id,
)
from .events import normalize_session_events
from .series import SESSION_CURVE_POINT_LIMIT, downsample_curve


DASHBOARD_SESSION_LIMIT = 20
SESSION_RETENTION_DAYS = 365
SESSION_RETENTION_ROWS = 1000
ARCHIVE_SUMMARY_SCHEMA = 1


SESSION_LOG_HEADERS = [
    "timestamp",
    "charger_id",
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
    "green_energy_kwh",
    "power_curve",
    "events",
    "source_energy_kwh",
    "effective_grid_cost",
    "accounting_coverage",
    "accounting_quality",
    "accounting_policy",
]
SESSION_EXPORT_HEADERS = [
    "charger_id",
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
    "green_energy_kwh",
    "source_energy_kwh",
    "effective_grid_cost",
    "accounting_coverage",
    "accounting_quality",
    "accounting_policy",
]


# All HA executor jobs share one history file. Serialize read/modify/write
# operations so delayed event updates cannot overwrite a completed session.
_HISTORY_LOCK = RLock()


def _journal_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}.retention.json")


def _atomic_json(path: Path, payload: dict) -> None:
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(payload, temporary, separators=(",", ":"), sort_keys=True)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _recover_history(path: Path) -> None:
    journal = _journal_path(path)
    if journal.is_file():
        payload = json.loads(journal.read_text(encoding="utf-8"))
        # This contains the *result*, never increments to apply a second time.
        _write_archive_summary(path, payload["summary"])
        _rewrite_rows(path, payload["headers"], payload["rows"])
        journal.unlink()


def _history_operation(operation):
    @wraps(operation)
    def locked(path, *args, **kwargs):
        with _HISTORY_LOCK:
            _recover_history(Path(path))
            return operation(path, *args, **kwargs)
    return locked


def _commit_history(path, headers, rows, summary):
    _atomic_json(_journal_path(path), {
        "headers": headers, "rows": rows, "summary": summary,
    })
    _recover_history(path)


def _archive_summary_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}.summary.json")


def _empty_archive_summary() -> dict[str, Any]:
    return {
        "schema": ARCHIVE_SUMMARY_SCHEMA,
        "total_energy_kwh": 0.0,
        "total_cost": 0.0,
        "total_green_energy_kwh": 0.0,
        "has_green_energy": False,
        "total_count": 0,
        "recent_session_ids": [],
    }


def _load_archive_summary(path: Path) -> dict[str, Any]:
    summary_path = _archive_summary_path(path)
    if not summary_path.is_file():
        return _empty_archive_summary()
    try:
        decoded = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return _empty_archive_summary()
    if not isinstance(decoded, dict) or decoded.get("schema") != ARCHIVE_SUMMARY_SCHEMA:
        return _empty_archive_summary()
    return {
        "schema": ARCHIVE_SUMMARY_SCHEMA,
        "recent_session_ids": [value for value in decoded.get("recent_session_ids", []) if isinstance(value, str)][-SESSION_RETENTION_ROWS:],
        "total_energy_kwh": _csv_float(decoded.get("total_energy_kwh")) or 0.0,
        "total_cost": _csv_float(decoded.get("total_cost")) or 0.0,
        "total_green_energy_kwh": (
            _csv_float(decoded.get("total_green_energy_kwh")) or 0.0
        ),
        "has_green_energy": bool(decoded.get("has_green_energy")),
        "total_count": max(0, int(_csv_float(decoded.get("total_count")) or 0)),
    }


def _write_archive_summary(path: Path, summary: dict[str, Any]) -> None:
    _atomic_json(_archive_summary_path(path), summary)


def _session_item(row: dict[str, Any], *, details: bool) -> dict[str, Any]:
    events = _session_events(row.get("events")) if details else []
    item = {
        "session_id": row.get("session_id") or None,
        "active": False,
        "start_time": row.get("start_time") or None,
        "end_time": row.get("end_time") or None,
        "energy_kwh": _csv_float(row.get("energy_kwh")),
        "green_energy_kwh": _csv_float(row.get("green_energy_kwh")),
        "source_energy_kwh": _accounting_sources(row.get("source_energy_kwh")),
        "effective_grid_cost": _csv_float(row.get("effective_grid_cost")),
        "accounting_coverage": _csv_float(row.get("accounting_coverage")),
        "accounting_quality": row.get("accounting_quality") or None,
        "accounting_policy": _accounting_policy(row.get("accounting_policy")),
        "cost": _csv_float(row.get("cost")),
        "duration_minutes": _csv_float(row.get("duration_minutes")),
        "authorized_identifier": row.get("authorized_identifier") or None,
        "detail_available": bool(row.get("power_curve") or row.get("events")),
    }
    if details:
        item["power_curve"] = _power_curve(
            row.get("power_curve"),
            event_times=(event.get("at") for event in events),
        )
        item["events"] = events
    return item


@_history_operation
def dashboard_session_data(
    path: str | Path,
    *,
    limit: int = DASHBOARD_SESSION_LIMIT,
) -> dict[str, Any]:
    """Read a bounded, display-safe history and totals from the session log."""
    csv_path = Path(path)
    archive = _load_archive_summary(csv_path)
    if not csv_path.is_file():
        return {
            "items": [],
            "total_energy_kwh": round(archive["total_energy_kwh"], 3),
            "total_cost": round(archive["total_cost"], 2),
            "total_green_energy_kwh": (
                round(archive["total_green_energy_kwh"], 3)
                if archive["has_green_energy"]
                else None
            ),
            "total_count": archive["total_count"],
        }

    items: list[dict[str, Any]] = []
    total_energy = float(archive["total_energy_kwh"])
    total_cost = float(archive["total_cost"])
    total_green = float(archive["total_green_energy_kwh"])
    has_green = bool(archive["has_green_energy"])
    with csv_path.open("r", newline="", encoding="utf-8") as source:
        for raw in csv.DictReader(source):
            row = normalize_session_row(raw)
            energy = _csv_float(row.get("energy_kwh"))
            cost = _csv_float(row.get("cost"))
            green = _csv_float(row.get("green_energy_kwh"))
            total_energy += energy or 0.0
            total_cost += cost or 0.0
            if green is not None:
                total_green += green
                has_green = True
            items.append(row)
    items.sort(key=lambda item: item.get("start_time") or "", reverse=True)
    bounded_rows = items[:max(1, min(limit, DASHBOARD_SESSION_LIMIT))]
    return {
        # Only the newest completed session is pushed with detail data. Older
        # selected rows are loaded on demand through the integration websocket.
        "items": [
            _session_item(row, details=index == 0)
            for index, row in enumerate(bounded_rows)
        ],
        "total_energy_kwh": round(total_energy, 3),
        "total_cost": round(total_cost, 2),
        "total_green_energy_kwh": round(total_green, 3) if has_green else None,
        "total_count": archive["total_count"] + len(items),
    }


@_history_operation
def session_detail_data(path: str | Path, session_id: str) -> dict[str, Any] | None:
    """Load one retained session with bounded curve and event details."""
    csv_path = Path(path)
    if not csv_path.is_file() or not session_id:
        return None
    with csv_path.open("r", newline="", encoding="utf-8") as source:
        rows = [normalize_session_row(row) for row in csv.DictReader(source)]
    for row in reversed(rows):
        if row.get("session_id") == session_id:
            return _session_item(row, details=True)
    return None


def _csv_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _accounting_json(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _accounting_sources(value: Any) -> dict | None:
    decoded = _accounting_json(value)
    keys = ("direct_solar", "direct_grid", "battery_unknown", "unknown")
    if not decoded or any(
        _csv_float(decoded.get(key)) is None
        or not isfinite(float(decoded[key]))
        or float(decoded[key]) < 0
        for key in keys
    ):
        return None
    return {key: float(decoded[key]) for key in keys}


def _accounting_policy(value: Any) -> dict | None:
    decoded = _accounting_json(value)
    if decoded.get("id") not in ("grid_first", "load_first", "mixed") or decoded.get("version") != 1:
        return None
    policy = {"id": decoded["id"], "version": 1}
    if decoded.get("topology") in ("grid_only", "pv", "pv_battery"):
        policy["topology"] = decoded["topology"]
    return policy


def _power_curve(
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


def _session_events(value: Any) -> list[dict[str, str]]:
    """Decode the bounded event contract without exposing arbitrary JSON."""
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return normalize_session_events(decoded)


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


def _target_headers(existing_headers: list[str] | None) -> list[str]:
    headers = list(existing_headers or ())
    for header in SESSION_LOG_HEADERS:
        if header not in headers:
            headers.append(header)
    return headers


def _rewrite_rows(
    path: Path,
    headers: list[str],
    rows: list[dict[str, Any]],
) -> None:
    temporary_path = None
    original_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            newline="",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            writer = csv.DictWriter(
                temporary,
                fieldnames=headers,
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(rows)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_path, original_mode)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _session_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(
            value.strip().replace("Z", "+00:00")
        ).date()
    except ValueError:
        return None


@_history_operation
def enforce_session_retention(
    path: str | Path,
    *,
    today: date | None = None,
    max_age_days: int = SESSION_RETENTION_DAYS,
    max_rows: int = SESSION_RETENTION_ROWS,
) -> int:
    """Prune old detail rows while carrying their KPI totals forward."""
    csv_path = Path(path)
    if not csv_path.is_file():
        return 0
    retention_date = (today or date.today()) - timedelta(days=max_age_days)
    with csv_path.open("r", newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        headers = _target_headers(list(reader.fieldnames or ()))
        rows = [normalize_session_row(row) for row in reader]

    retained: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for row in rows:
        started_on = _session_date(row.get("start_time"))
        if started_on is not None and started_on < retention_date:
            removed.append(row)
        else:
            retained.append(row)

    if len(retained) > max_rows:
        newest_indices = {
            index
            for index, _ in sorted(
                enumerate(retained),
                key=lambda item: (
                    _session_date(item[1].get("start_time")) or date.max,
                    item[0],
                ),
                reverse=True,
            )[:max_rows]
        }
        overflow = []
        bounded = []
        for index, row in enumerate(retained):
            (bounded if index in newest_indices else overflow).append(row)
        retained = bounded
        removed.extend(overflow)

    if not removed:
        return 0

    archive = _load_archive_summary(csv_path)
    for row in removed:
        archive["total_energy_kwh"] += _csv_float(row.get("energy_kwh")) or 0.0
        archive["total_cost"] += _csv_float(row.get("cost")) or 0.0
        green = _csv_float(row.get("green_energy_kwh"))
        if green is not None:
            archive["total_green_energy_kwh"] += green
            archive["has_green_energy"] = True
        archive["total_count"] += 1

    archive["total_energy_kwh"] = round(archive["total_energy_kwh"], 3)
    archive["total_cost"] = round(archive["total_cost"], 2)
    archive["total_green_energy_kwh"] = round(
        archive["total_green_energy_kwh"], 3
    )
    _commit_history(csv_path, headers, retained, archive)
    return len(removed)


@_history_operation
def append_session_row(path: str | Path, row: dict[str, Any]) -> None:
    """Append one row and migrate an older CSV schema atomically if needed."""
    csv_path = Path(path)
    normalized_row = normalize_session_row(row)
    for key in ("source_energy_kwh", "accounting_policy"):
        if isinstance(normalized_row.get(key), dict):
            normalized_row[key] = json.dumps(normalized_row[key], separators=(",", ":"))
    events = _session_events(normalized_row.get("events"))
    normalized_row["events"] = json.dumps(events, separators=(",", ":"))
    normalized_row["power_curve"] = json.dumps(
        _power_curve(
            normalized_row.get("power_curve"),
            event_times=(event.get("at") for event in events),
        ),
        separators=(",", ":"),
    )
    file_exists = csv_path.is_file() and csv_path.stat().st_size > 0

    headers = list(SESSION_LOG_HEADERS)
    rows = []
    if file_exists:
        with csv_path.open("r", newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            headers = _target_headers(list(reader.fieldnames or ()))
            rows = [normalize_session_row(existing) for existing in reader]
    archive = _load_archive_summary(csv_path)
    # Only explicit identities support replay; legacy inferred rows may collide.
    session_id = row.get("session_id")
    if session_id and (
        session_id in archive["recent_session_ids"]
        or any(existing.get("session_id") == session_id for existing in rows)
    ):
        enforce_session_retention(csv_path)
        return
    if session_id:
        archive["recent_session_ids"] = (
            archive["recent_session_ids"] + [session_id]
        )[-SESSION_RETENTION_ROWS:]
    _commit_history(csv_path, headers, rows + [normalized_row], archive)
    enforce_session_retention(csv_path)


@_history_operation
def update_session_events(
    path: str | Path,
    session_id: str,
    events: Any,
) -> bool:
    """Atomically update events when unplugging follows the logged stop."""
    csv_path = Path(path)
    if not csv_path.is_file() or not session_id:
        return False

    with csv_path.open("r", newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        headers = _target_headers(list(reader.fieldnames or ()))
        rows = [normalize_session_row(row) for row in reader]

    encoded_events = json.dumps(
        normalize_session_events(events),
        separators=(",", ":"),
    )
    updated = False
    for row in reversed(rows):
        if row.get("session_id") != session_id:
            continue
        if row.get("events") != encoded_events:
            row["events"] = encoded_events
            updated = True
        break
    if updated:
        _rewrite_rows(csv_path, headers, rows)
    return updated


@_history_operation
def export_session_rows(
    source_path: str | Path,
    target_path: str | Path,
    *,
    date_from: datetime,
    date_to: datetime,
) -> int:
    """Atomically export normalized rows within one inclusive date range.

    The export is assembled beside its destination and then replaced in one
    filesystem operation.  Readers therefore see either the previous complete
    export or the new complete export, never a half-written CSV.
    """
    source = Path(source_path)
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    if source.is_file():
        with source.open("r", newline="", encoding="utf-8") as source_file:
            reader = csv.DictReader(source_file)
            for row in reader:
                try:
                    row_date = datetime.strptime(
                        row["start_time"],
                        "%Y-%m-%d %H:%M:%S",
                    )
                except (KeyError, TypeError, ValueError):
                    # One malformed historical row must not prevent all valid
                    # sessions from being exported.
                    continue
                if date_from <= row_date <= date_to:
                    rows.append(normalize_session_row(row))

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            newline="",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            writer = csv.DictWriter(
                temporary,
                fieldnames=SESSION_EXPORT_HEADERS,
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(rows)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

    return len(rows)
