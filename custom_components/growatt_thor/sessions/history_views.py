"""Bounded dashboard and detail projections from retained history."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .archive_summary import (
    archive_partial_count,
    belongs_to_entry,
    load_archive_summary,
    scoped_archive,
    session_green,
)
from .display_times import session_times
from .history_rows import (
    accounting_policy,
    accounting_sources,
    csv_float,
    normalize_session_row,
    power_curve,
    session_events,
)
from .history_store import history_operation
from .telemetry import CONTEXT_CURVES, context_curves

DASHBOARD_SESSION_LIMIT = 20


def session_item(row: dict[str, Any], *, details: bool, time_zone: str = "UTC") -> dict[str, Any]:
    events = session_events(row.get("events")) if details else []
    item = {
        "session_id": row.get("session_id") or None,
        "active": False,
        "start_time": row.get("start_time") or None,
        "end_time": row.get("end_time") or None,
        "energy_kwh": csv_float(row.get("energy_kwh")),
        "green_energy_kwh": csv_float(row.get("green_energy_kwh")),
        "source_energy_kwh": accounting_sources(row.get("source_energy_kwh")),
        "effective_grid_cost": csv_float(row.get("effective_grid_cost")),
        "accounting_coverage": csv_float(row.get("accounting_coverage")),
        "accounting_quality": row.get("accounting_quality") or None,
        "accounting_policy": accounting_policy(row.get("accounting_policy")),
        "cost": csv_float(row.get("cost")),
        "duration_minutes": csv_float(row.get("duration_minutes")),
        "authorized_identifier": row.get("authorized_identifier") or None,
        "authorized_alias": row.get("authorized_alias") or None,
        "detail_available": bool(row.get("power_curve") or row.get("events")),
    }
    if details:
        item["power_curve"] = power_curve(
            row.get("power_curve"),
            event_times=(event.get("at") for event in events),
        )
        decoded_curves = {}
        for key in CONTEXT_CURVES:
            try:
                decoded_curves[key] = (
                    json.loads(row[key]) if isinstance(row.get(key), str) else row.get(key)
                )
            except (ValueError, TypeError):
                continue
        if row.get("site_house_load_source") in (
            "configured_sensor",
            "site_balance",
            "mixed",
        ):
            item["site_house_load_source"] = row["site_house_load_source"]
        item.update(
            context_curves(decoded_curves, event_times=(event.get("at") for event in events))
        )
        item["events"] = events
    return session_times(item, time_zone)


@history_operation
def dashboard_session_data(
    path: str | Path,
    *,
    limit: int = DASHBOARD_SESSION_LIMIT,
    source_instance_id: str | None = None,
    charge_point_id: str | None = None,
    include_unassigned_archive: bool = False,
    time_zone: str = "UTC",
) -> dict[str, Any]:
    """Read a bounded, display-safe history and totals from the session log."""
    csv_path = Path(path)
    archive = load_archive_summary(csv_path)
    if source_instance_id is not None:
        archive = scoped_archive(
            archive, source_instance_id, charge_point_id, include_unassigned_archive
        )
    if not csv_path.is_file():
        return {
            "items": [],
            "total_energy_kwh": round(archive["total_energy_kwh"], 3),
            "total_cost": round(archive["total_cost"], 2),
            "total_green_energy_kwh": (
                round(archive["total_green_energy_kwh"], 3) if archive["has_green_energy"] else None
            ),
            "total_count": archive["total_count"],
            "total_green_partial": archive_partial_count(archive) > 0,
        }

    items: list[dict[str, Any]] = []
    total_energy = float(archive["total_energy_kwh"])
    total_cost = float(archive["total_cost"])
    total_green = float(archive["total_green_energy_kwh"])
    has_green = bool(archive["has_green_energy"])
    partial_count = archive_partial_count(archive)
    with csv_path.open("r", newline="", encoding="utf-8") as source:
        for raw in csv.DictReader(source):
            row = normalize_session_row(raw)
            if not belongs_to_entry(row, source_instance_id, charge_point_id):
                continue
            energy = csv_float(row.get("energy_kwh"))
            cost = csv_float(row.get("cost"))
            green, partial = session_green(row)
            partial_count += int(partial)
            total_energy += energy or 0.0
            total_cost += cost or 0.0
            if green is not None:
                total_green += green
                has_green = True
            items.append(row)
    items.sort(key=lambda item: item.get("start_time") or "", reverse=True)
    bounded_rows = items[: max(1, min(limit, DASHBOARD_SESSION_LIMIT))]
    return {
        # Only the newest completed session is pushed with detail data. Older
        # selected rows are loaded on demand through the integration websocket.
        "items": [
            session_item(row, details=index == 0, time_zone=time_zone)
            for index, row in enumerate(bounded_rows)
        ],
        "total_energy_kwh": round(total_energy, 3),
        "total_cost": round(total_cost, 2),
        "total_green_energy_kwh": round(total_green, 3) if has_green else None,
        "total_green_partial": partial_count > 0,
        "total_count": archive["total_count"] + len(items),
    }


@history_operation
def session_detail_data(
    path: str | Path,
    session_id: str,
    *,
    source_instance_id=None,
    charge_point_id=None,
    time_zone="UTC",
) -> dict[str, Any] | None:
    """Load one retained session with bounded curve and event details."""
    csv_path = Path(path)
    if not csv_path.is_file() or not session_id:
        return None
    with csv_path.open("r", newline="", encoding="utf-8") as source:
        rows = [normalize_session_row(row) for row in csv.DictReader(source)]
    for row in reversed(rows):
        if row.get("session_id") == session_id and belongs_to_entry(
            row, source_instance_id, charge_point_id
        ):
            return session_item(row, details=True, time_zone=time_zone)
    return None
