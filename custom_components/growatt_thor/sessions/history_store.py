"""Journaled history writes and one shared reentrant history lock."""

from __future__ import annotations

import csv
import json
import os
import stat
import tempfile
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Any

# All executor jobs share one history file. Serialize read/modify/write
# operations so delayed event updates cannot overwrite a completed session.


_HISTORY_LOCK = RLock()


def _journal_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}.retention.json")


def _atomic_json(path: Path, payload: dict) -> None:
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
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
        write_archive_summary(path, payload["summary"])
        rewrite_rows(path, payload["headers"], payload["rows"])
        journal.unlink()


def history_operation(operation):
    @wraps(operation)
    def locked(path, *args, **kwargs):
        with _HISTORY_LOCK:
            _recover_history(Path(path))
            return operation(path, *args, **kwargs)

    return locked


def commit_history(path, headers, rows, summary):
    _atomic_json(
        _journal_path(path),
        {
            "headers": headers,
            "rows": rows,
            "summary": summary,
        },
    )
    _recover_history(path)


def archive_summary_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}.summary.json")


def write_archive_summary(path: Path, summary: dict[str, Any]) -> None:
    _atomic_json(archive_summary_path(path), summary)


def rewrite_rows(
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
