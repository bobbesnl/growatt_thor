"""Backward-compatible charging session CSV helpers."""
from __future__ import annotations

import csv
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

from .session_identity import (
    SOURCE_LEGACY_UNKNOWN,
    build_session_id,
)


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
]


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
    original_mode = stat.S_IMODE(path.stat().st_mode)
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
        os.chmod(temporary_path, original_mode)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def append_session_row(path: str | Path, row: dict[str, Any]) -> None:
    """Append one row and migrate an older CSV schema atomically if needed."""
    csv_path = Path(path)
    normalized_row = normalize_session_row(row)
    file_exists = csv_path.is_file() and csv_path.stat().st_size > 0

    headers = list(SESSION_LOG_HEADERS)
    if file_exists:
        rows_to_migrate = None
        with csv_path.open("r", newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            existing_headers = list(reader.fieldnames or ())
            headers = _target_headers(existing_headers)
            if headers != existing_headers:
                rows_to_migrate = [
                    normalize_session_row(existing) for existing in reader
                ]
        if rows_to_migrate is not None:
            _rewrite_rows(csv_path, headers, rows_to_migrate)

    with csv_path.open("a", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(
            target,
            fieldnames=headers,
            extrasaction="ignore",
        )
        if not file_exists:
            writer.writeheader()
        writer.writerow(normalized_row)
