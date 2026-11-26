"""Build target request records without owning execution or persistence."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import datetime
from typing import TypedDict, Unpack
from uuid import uuid4
from zoneinfo import ZoneInfo

from .model import NATIVE_STOP_VERIFIED, ChargingTarget, TargetState
from .schedule import iso_utc, reservation_expiry


class TargetHistoryEntry(TypedDict):
    """Short summary of a replaced request, kept for reconciliation."""

    request_id: str | None
    kind: str | None
    value: str | None
    state: str | None
    activation: str | None
    recurrence: str | None
    scheduled_for: str | None
    updated_at: str | None


class TargetRecord(TypedDict, total=False):
    """Persisted charging-target request.

    The record is stored as a plain dictionary under the charging-target
    storage key; its key names are part of that storage contract. Only keys
    for the selected start kind are present: reservations add the reservation
    fields, daily schedules add the local time and the last run.
    """

    kind: str
    value: str
    unit: str
    request_id: str
    state: str
    scheduled_for: str
    time_zone: str
    recurrence: str
    updated_at: str
    enforcement_verified: bool
    activation: str
    connection_started_at: str | None
    local_time: str
    reservation_id: int
    reservation_expiry: str
    last_run_at: str
    last_run_state: str
    previous_requests: list[TargetHistoryEntry]


def updated_record(record: TargetRecord, **changes: Unpack[TargetRecord]) -> TargetRecord:
    """Return a copy with changed fields; existing keys keep their position."""
    return {**record, **changes}


class InvalidReservationExpiry(ValueError):
    """A reservation expiry could not be built from the validated start time."""


def _request_history(previous: TargetRecord | None) -> list[TargetHistoryEntry]:
    if not previous:
        return []
    return [
        *previous.get("previous_requests", [])[-4:],
        TargetHistoryEntry(
            request_id=previous.get("request_id"),
            kind=previous.get("kind"),
            value=previous.get("value"),
            state=previous.get("state"),
            activation=previous.get("activation"),
            recurrence=previous.get("recurrence"),
            scheduled_for=previous.get("scheduled_for"),
            updated_at=previous.get("updated_at"),
        ),
    ]


def new_target_request(
    target: ChargingTarget,
    *,
    activation: str,
    now: Callable[[], str],
    connection_started_at: str | None,
    previous: TargetRecord | None,
    replacing: bool,
) -> TargetRecord:
    diagnostic = target.diagnostic()
    request: TargetRecord = {
        "kind": diagnostic["kind"],
        "value": diagnostic["value"],
        "unit": diagnostic["unit"],
        "request_id": uuid4().hex,
        "state": TargetState.QUEUED,
        "updated_at": now(),
        "enforcement_verified": NATIVE_STOP_VERIFIED[target.kind],
        "activation": {
            "plug": "plug_and_charge",
            "rfid": "rfid",
            "remote": "remote_start",
        }[activation],
        "connection_started_at": connection_started_at,
    }
    if replacing:
        request["previous_requests"] = _request_history(previous)
    return request


def new_scheduled_request(
    target: ChargingTarget,
    *,
    start_at: datetime,
    time_zone: str,
    recurrence: str,
    now: Callable[[], str],
    previous: TargetRecord | None,
    replacing: bool,
) -> TargetRecord:
    diagnostic = target.diagnostic()
    request: TargetRecord = {
        "kind": diagnostic["kind"],
        "value": diagnostic["value"],
        "unit": diagnostic["unit"],
        "request_id": uuid4().hex,
        "state": TargetState.RESERVATION_QUEUED if recurrence == "once" else TargetState.SCHEDULED,
        "scheduled_for": iso_utc(start_at),
        "time_zone": time_zone,
        "recurrence": recurrence,
        "updated_at": now(),
        "enforcement_verified": NATIVE_STOP_VERIFIED[target.kind],
        "activation": (
            "charger_reservation_remote_start" if recurrence == "once" else "daily_remote_start"
        ),
    }
    if recurrence == "daily":
        request["local_time"] = start_at.astimezone(ZoneInfo(time_zone)).strftime("%H:%M:%S")
    if recurrence == "once":
        request["reservation_id"] = secrets.randbelow(2_000_000_000) + 1
        try:
            request["reservation_expiry"] = reservation_expiry(start_at, time_zone)
        except ValueError as exc:
            raise InvalidReservationExpiry(str(exc)) from exc
    if replacing:
        request["previous_requests"] = _request_history(previous)
    return request
