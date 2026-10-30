"""Build target request records without owning execution or persistence."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from .model import NATIVE_STOP_VERIFIED, ChargingTarget, TargetState
from .schedule import iso_utc, reservation_expiry

TargetRecord = dict[str, Any]


class InvalidReservationExpiry(ValueError):
    """A reservation expiry could not be built from the validated start time."""


def _request_history(previous: TargetRecord | None) -> list[TargetRecord]:
    if not previous:
        return []
    fields = (
        "request_id",
        "kind",
        "value",
        "state",
        "activation",
        "recurrence",
        "scheduled_for",
        "updated_at",
    )
    return [
        *previous.get("previous_requests", [])[-4:],
        {key: previous.get(key) for key in fields},
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
    request = {
        **target.diagnostic(),
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
    request = {
        **target.diagnostic(),
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
