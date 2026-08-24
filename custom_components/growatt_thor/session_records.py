"""Structured models for Growatt currentrecord and frozenrecord payloads."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl


REDACTED = "<redacted>"
_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_KNOWN_FIELDS = frozenset(
    {
        "id",
        "connectorId",
        "chargemode",
        "plugtime",
        "unplugtime",
        "starttime",
        "endtime",
        "costenergy",
        "costmoney",
        "transactionId",
        "workmode",
    }
)


def _optional_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _optional_datetime(value: str | None) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.strptime(value, _DATETIME_FORMAT)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class GrowattSessionRecord:
    """One Growatt session record with raw and normalized values."""

    message_id: str
    raw_payload: str
    field_items: tuple[tuple[str, str], ...]
    parse_errors: tuple[str, ...]

    @property
    def fields(self) -> dict[str, tuple[str, ...]]:
        """Return all values grouped by key without dropping duplicates."""
        grouped: dict[str, list[str]] = {}
        for key, value in self.field_items:
            grouped.setdefault(key, []).append(value)
        return {key: tuple(values) for key, values in grouped.items()}

    def first(self, key: str, default: str = "") -> str:
        """Return the first value for a Growatt field."""
        for field_key, value in self.field_items:
            if field_key == key:
                return value
        return default

    @property
    def record_id(self) -> str:
        return self.first("id")

    @property
    def connector_id(self) -> str:
        return self.first("connectorId")

    @property
    def transaction_id(self) -> str:
        return self.first("transactionId")

    @property
    def charge_mode(self) -> str:
        return self.first("chargemode")

    @property
    def work_mode(self) -> str:
        return self.first("workmode")

    @property
    def plug_time(self) -> str:
        return self.first("plugtime")

    @property
    def unplug_time(self) -> str:
        return self.first("unplugtime")

    @property
    def start_time(self) -> str:
        return self.first("starttime")

    @property
    def end_time(self) -> str:
        return self.first("endtime")

    @property
    def energy_wh(self) -> float | None:
        return _optional_float(self.first("costenergy"))

    @property
    def energy_kwh(self) -> float | None:
        value = self.energy_wh
        return value / 1000 if value is not None else None

    @property
    def cost_minor(self) -> float | None:
        return _optional_float(self.first("costmoney"))

    @property
    def cost(self) -> float | None:
        value = self.cost_minor
        return value / 100 if value is not None else None

    @property
    def duration_minutes(self) -> float | None:
        start = _optional_datetime(self.start_time)
        end = _optional_datetime(self.end_time)
        if start is None or end is None:
            return None
        return round((end - start).total_seconds() / 60, 1)

    @property
    def dedup_key(self) -> tuple[str, str] | None:
        """Identify the same session across currentrecord and frozenrecord."""
        if not self.transaction_id or not self.end_time:
            return None
        return (self.transaction_id, self.end_time)

    def as_dict(self, *, redact: bool = False) -> dict[str, Any]:
        """Return a JSON-safe representation for diagnostics."""
        fields = {
            key: [
                value if not redact or key in _KNOWN_FIELDS else REDACTED
                for value in values
            ]
            for key, values in self.fields.items()
        }
        return {
            "message_id": self.message_id,
            "raw_payload": REDACTED if redact else self.raw_payload,
            "fields": fields,
            "normalized": {
                "record_id": self.record_id,
                "connector_id": self.connector_id,
                "transaction_id": self.transaction_id,
                "charge_mode": self.charge_mode,
                "work_mode": self.work_mode,
                "plug_time": self.plug_time,
                "unplug_time": self.unplug_time,
                "start_time": self.start_time,
                "end_time": self.end_time,
                "energy_wh": self.energy_wh,
                "energy_kwh": self.energy_kwh,
                "cost_minor": self.cost_minor,
                "cost": self.cost,
                "duration_minutes": self.duration_minutes,
            },
            "parse_errors": list(self.parse_errors),
            "unknown_fields": sorted(set(self.fields) - _KNOWN_FIELDS),
        }


def parse_growatt_session_record(
    message_id: str,
    payload: str,
) -> GrowattSessionRecord:
    """Parse a Growatt query-string session payload without losing fields."""
    if message_id not in ("currentrecord", "frozenrecord"):
        raise ValueError(f"unsupported Growatt session messageId: {message_id}")
    if not isinstance(payload, str):
        raise TypeError("Growatt session payload must be a string")

    field_items = tuple(parse_qsl(payload, keep_blank_values=True))
    first_values: dict[str, str] = {}
    for key, value in field_items:
        first_values.setdefault(key, value)

    errors = []
    for key in ("costenergy", "costmoney"):
        value = first_values.get(key)
        if value not in (None, "") and _optional_float(value) is None:
            errors.append(f"invalid numeric value for {key}: {value!r}")
    for key in ("plugtime", "unplugtime", "starttime", "endtime"):
        value = first_values.get(key)
        if value not in (None, "") and _optional_datetime(value) is None:
            errors.append(f"invalid timestamp for {key}: {value!r}")

    return GrowattSessionRecord(
        message_id=message_id,
        raw_payload=payload,
        field_items=field_items,
        parse_errors=tuple(errors),
    )


def session_record_diagnostics(snapshot: dict[str, Any] | None) -> Any:
    """Serialize one retained coordinator snapshot with safe redaction."""
    if snapshot is None:
        return None
    record = snapshot.get("record")
    if not isinstance(record, GrowattSessionRecord):
        return None
    return {
        "received_at": snapshot.get("received_at"),
        "record": record.as_dict(redact=True),
    }
