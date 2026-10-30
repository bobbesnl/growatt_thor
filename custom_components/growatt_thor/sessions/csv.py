"""Session history writes, late event updates and retention."""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .archive_summary import add_archive_row, empty_archive_summary, load_archive_summary
from .events import normalize_session_events
from .history_rows import (
    SESSION_LOG_HEADERS,
    SESSION_RETENTION_DAYS,
    SESSION_RETENTION_ROWS,
    normalize_session_row,
    power_curve,
    session_date,
    session_events,
    target_headers,
)
from .history_store import commit_history, history_operation, rewrite_rows


@history_operation
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
        headers = target_headers(list(reader.fieldnames or ()))
        rows = [normalize_session_row(row) for row in reader]

    retained: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for row in rows:
        started_on = session_date(row.get("start_time"))
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
                    session_date(item[1].get("start_time")) or date.max,
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

    archive = load_archive_summary(csv_path)
    for row in removed:
        owner = (
            ("entry:" + row["source_instance_id"])
            if row.get("source_instance_id")
            else ("charger:" + str(row.get("charger_id", "")))
        )
        bucket = archive.setdefault("owners", {}).setdefault(owner, empty_archive_summary())
        add_archive_row(bucket, row)
        add_archive_row(archive, row)

    archive["total_energy_kwh"] = round(archive["total_energy_kwh"], 3)
    archive["total_cost"] = round(archive["total_cost"], 2)
    archive["total_green_energy_kwh"] = round(archive["total_green_energy_kwh"], 3)
    commit_history(csv_path, headers, retained, archive)
    return len(removed)


@history_operation
def append_session_row(path: str | Path, row: dict[str, Any]) -> None:
    """Append one row and migrate an older CSV schema atomically if needed."""
    csv_path = Path(path)
    normalized_row = normalize_session_row(row)
    for key in ("source_energy_kwh", "accounting_policy"):
        if isinstance(normalized_row.get(key), dict):
            normalized_row[key] = json.dumps(normalized_row[key], separators=(",", ":"))
    events = session_events(normalized_row.get("events"))
    normalized_row["events"] = json.dumps(events, separators=(",", ":"))
    normalized_row["power_curve"] = json.dumps(
        power_curve(
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
            headers = target_headers(list(reader.fieldnames or ()))
            rows = [normalize_session_row(existing) for existing in reader]
    archive = load_archive_summary(csv_path)
    # Only explicit identities support replay; legacy inferred rows may collide.
    session_id = row.get("session_id")
    if session_id and (
        session_id in archive["recent_session_ids"]
        or any(existing.get("session_id") == session_id for existing in rows)
    ):
        enforce_session_retention(csv_path)
        return
    if session_id:
        archive["recent_session_ids"] = (archive["recent_session_ids"] + [session_id])[
            -SESSION_RETENTION_ROWS:
        ]
    commit_history(csv_path, headers, rows + [normalized_row], archive)
    enforce_session_retention(csv_path)


@history_operation
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
        headers = target_headers(list(reader.fieldnames or ()))
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
        rewrite_rows(csv_path, headers, rows)
    return updated
