"""Retained totals and per-entry ownership for archived session rows."""

from __future__ import annotations

import json
from math import isfinite
from pathlib import Path
from typing import Any

from .history_rows import SESSION_RETENTION_ROWS, accounting_sources, csv_float
from .history_store import archive_summary_path

ARCHIVE_SUMMARY_SCHEMA = 1


def empty_archive_summary() -> dict[str, Any]:
    return {
        "schema": ARCHIVE_SUMMARY_SCHEMA,
        "total_energy_kwh": 0.0,
        "total_cost": 0.0,
        "total_green_energy_kwh": 0.0,
        "has_green_energy": False,
        "green_partial_count": 0,
        "total_count": 0,
        "recent_session_ids": [],
        "owners": {},
    }


def load_archive_summary(path: Path) -> dict[str, Any]:
    summary_path = archive_summary_path(path)
    if not summary_path.is_file():
        return empty_archive_summary()
    try:
        decoded = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return empty_archive_summary()
    if not isinstance(decoded, dict) or decoded.get("schema") != ARCHIVE_SUMMARY_SCHEMA:
        return empty_archive_summary()
    return {
        "schema": ARCHIVE_SUMMARY_SCHEMA,
        "owners": decoded.get("owners", {}) if isinstance(decoded.get("owners"), dict) else {},
        "recent_session_ids": [
            value for value in decoded.get("recent_session_ids", []) if isinstance(value, str)
        ][-SESSION_RETENTION_ROWS:],
        "total_energy_kwh": csv_float(decoded.get("total_energy_kwh")) or 0.0,
        "total_cost": csv_float(decoded.get("total_cost")) or 0.0,
        "total_green_energy_kwh": (csv_float(decoded.get("total_green_energy_kwh")) or 0.0),
        "has_green_energy": bool(decoded.get("has_green_energy")),
        "green_partial_count": archive_partial_count(decoded),
        "total_count": max(0, int(csv_float(decoded.get("total_count")) or 0)),
    }


def belongs_to_entry(row, source_instance_id, charge_point_id):
    if source_instance_id is None:
        return True
    if row.get("source_instance_id"):
        return row["source_instance_id"] == source_instance_id
    return bool(charge_point_id and row.get("charger_id") == charge_point_id)


def archive_partial_count(bucket: dict[str, Any]) -> int:
    # Older summaries discarded source details, so their completeness cannot
    # be reconstructed. Preserve the known total as a qualified lower bound.
    count = max(0, int(csv_float(bucket.get("total_count")) or 0))
    value = csv_float(bucket.get("green_partial_count"))
    return min(count, max(0, int(value))) if value is not None and isfinite(value) else count


def session_green(row: dict[str, Any]) -> tuple[float | None, bool]:
    """Match the row display: exact green or balanced known solar as a floor."""
    reported = csv_float(row.get("green_energy_kwh"))
    if reported is not None and isfinite(reported) and reported >= 0:
        return reported, False
    energy = csv_float(row.get("energy_kwh"))
    sources = accounting_sources(row.get("source_energy_kwh"))
    if (
        sources is not None
        and energy is not None
        and isfinite(energy)
        and energy > 0
        and abs(sum(sources.values()) - energy) <= 0.001
        and sum(sources[key] for key in ("direct_solar", "direct_grid", "battery_unknown")) > 0
    ):
        return sources["direct_solar"], sources["unknown"] > 1e-9
    return None, energy is None or not isfinite(energy) or energy > 0


def add_archive_row(bucket, row):
    green, partial = session_green(row)
    bucket["green_partial_count"] = archive_partial_count(bucket) + int(partial)
    bucket["total_energy_kwh"] += csv_float(row.get("energy_kwh")) or 0.0
    bucket["total_cost"] += csv_float(row.get("cost")) or 0.0
    if green is not None:
        bucket["total_green_energy_kwh"] += green
        bucket["has_green_energy"] = True
    bucket["total_count"] += 1


def scoped_archive(archive, entry_id, charge_point_id, include_unassigned=False):
    result = empty_archive_summary()
    if include_unassigned:
        # Old 2.0 summaries had no owner labels. Preserve them only for the
        # sole entry present at migration; never duplicate them across chargers.
        owners = archive.get("owners", {}).values()
        for field in (
            "total_energy_kwh",
            "total_cost",
            "total_green_energy_kwh",
            "total_count",
        ):
            result[field] = archive[field] - sum(
                csv_float(bucket.get(field)) or 0 for bucket in owners
            )
        result["has_green_energy"] = (
            bool(archive.get("has_green_energy")) and result["total_count"] > 0
        )
        result["green_partial_count"] = max(
            0,
            archive_partial_count(archive)
            - sum(archive_partial_count(bucket) for bucket in owners),
        )
    keys = ["entry:" + entry_id]
    if charge_point_id:
        keys.append("charger:" + charge_point_id)
    for key in keys:
        bucket = archive.get("owners", {}).get(key, {})
        for field in (
            "total_energy_kwh",
            "total_cost",
            "total_green_energy_kwh",
            "total_count",
        ):
            result[field] += csv_float(bucket.get(field)) or 0
        result["has_green_energy"] |= bool(bucket.get("has_green_energy"))
        result["green_partial_count"] += archive_partial_count(bucket)
    return result
