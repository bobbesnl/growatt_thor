"""Short-lived, unguessable session downloads with restart-safe cleanup."""

from __future__ import annotations

import asyncio
import csv
import logging
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from ..timestamps import parse_utc, utc_timestamp
from .history_rows import SESSION_EXPORT_HEADERS, normalize_session_row
from .history_store import history_operation

EXPORT_LIFETIME_SECONDS = 15 * 60
_CLEANUP_KEY = "growatt_thor_export_cleanup"
_LOGGER = logging.getLogger(__name__)


def new_export_path(directory: str) -> Path:
    return Path(directory) / f"growatt_thor_export_{uuid4().hex}.csv"


def cleanup_expired_exports(directory: str, *, now: float | None = None) -> None:
    """Include exports from older releases and interrupted HA processes."""
    current = time.time() if now is None else now
    for path in Path(directory).glob("growatt_thor_export_*.csv"):
        try:
            if path.is_file() and current - path.stat().st_mtime >= EXPORT_LIFETIME_SECONDS:
                path.unlink(missing_ok=True)
        except OSError:
            _LOGGER.exception("Could not expire session export")


def ensure_export_cleanup(hass) -> None:
    """Start one HA-owned worker; HA shutdown cancels it automatically."""
    task = hass.data.get(_CLEANUP_KEY)
    if task is not None and not task.done():
        return

    async def clean():
        while True:
            await hass.async_add_executor_job(cleanup_expired_exports, hass.config.path("www"))
            await asyncio.sleep(60)

    hass.data[_CLEANUP_KEY] = hass.async_create_background_task(
        clean(), "growatt_thor_export_cleanup"
    )


@history_operation
def export_session_rows(
    source_path: str | Path,
    target_path: str | Path,
    *,
    date_from: datetime,
    date_to: datetime,
    time_zone: str = "UTC",
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
                    row_date = parse_utc(
                        row["start_time"].replace("Z", "+00:00"), allow_naive=True, normalize=False
                    )
                    if row_date is None:
                        continue
                    if row_date.tzinfo is not None:
                        row_date = row_date.astimezone(ZoneInfo(time_zone)).replace(tzinfo=None)
                except (KeyError, TypeError, ValueError):
                    # One malformed historical row must not prevent all valid
                    # sessions from being exported.
                    continue
                if date_from <= row_date <= date_to:
                    exported = normalize_session_row(row)
                    for key in ("timestamp", "start_time", "end_time"):
                        exported[key] = utc_timestamp(exported.get(key), time_zone) or ""
                    rows.append(exported)

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
            writer.writerows(
                {key: sanitize_export_cell(value) for key, value in row.items()} for row in rows
            )
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

    return len(rows)


def sanitize_export_cell(value: Any) -> Any:
    """Keep spreadsheet applications from treating user data as formulas."""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        return "'" + value
    return value
