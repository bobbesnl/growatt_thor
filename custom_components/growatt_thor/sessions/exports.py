"""Short-lived, unguessable session downloads with restart-safe cleanup."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import time
from uuid import uuid4

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

    hass.data[_CLEANUP_KEY] = hass.async_create_background_task(clean(), "growatt_thor_export_cleanup")
