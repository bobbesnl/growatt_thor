"""Correlate OCPP transactions with Growatt session data."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from .session_identity import (
    SOURCE_EXTERNAL_OR_UNKNOWN,
    SOURCE_HOME_ASSISTANT,
    build_session_id,
)


CORRELATION_MATCHED = "matched"
CORRELATION_OCPP_ONLY = "ocpp_only"
CORRELATION_GROWATT_ONLY = "growatt_only"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timestamp(value: Any) -> datetime | None:
    text = _optional_text(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _at_or_after(value: Any, lower_bound: datetime | None) -> bool:
    timestamp = _timestamp(value)
    if timestamp is None or lower_bound is None:
        return True
    if (timestamp.tzinfo is None) != (lower_bound.tzinfo is None):
        timestamp = timestamp.replace(tzinfo=None)
        lower_bound = lower_bound.replace(tzinfo=None)
    return timestamp >= lower_bound


def _at_or_before(value: Any, upper_bound: datetime | None) -> bool:
    timestamp = _timestamp(value)
    if timestamp is None or upper_bound is None:
        return True
    if (timestamp.tzinfo is None) != (upper_bound.tzinfo is None):
        timestamp = timestamp.replace(tzinfo=None)
        upper_bound = upper_bound.replace(tzinfo=None)
    return timestamp <= upper_bound


def _request(snapshot: Any) -> Mapping[str, Any]:
    return _mapping(_mapping(snapshot).get("request"))


def _transaction_id(transaction: Mapping[str, Any]) -> str | None:
    start = _mapping(transaction.get("start"))
    response = _mapping(start.get("response"))
    stop_request = _request(transaction.get("stop"))
    return _optional_text(
        response.get("transaction_id", stop_request.get("transaction_id"))
    )


def _record_info(snapshot: Any) -> dict[str, Any] | None:
    snapshot_mapping = _mapping(snapshot)
    record = snapshot_mapping.get("record")
    if record is None:
        return None

    message_id = _optional_text(getattr(record, "message_id", None))
    if message_id not in ("currentrecord", "frozenrecord"):
        return None

    return {
        "snapshot": snapshot_mapping,
        "record": record,
        "message_id": message_id,
        "received_at": _optional_text(snapshot_mapping.get("received_at")),
        "transaction_id": _optional_text(
            getattr(record, "transaction_id", None)
        ),
        "dedup_key": getattr(record, "dedup_key", None),
    }


def _select_records(
    snapshots: Sequence[Any],
    transaction_id: str | None,
    transaction_started_at: str | None,
) -> list[dict[str, Any]]:
    records = [
        info
        for snapshot in snapshots
        if (info := _record_info(snapshot)) is not None
    ]
    if transaction_id is not None:
        started_at = _timestamp(transaction_started_at)
        return [
            info
            for info in records
            if info["transaction_id"] == transaction_id
            and _at_or_after(info["received_at"], started_at)
        ]
    if not records:
        return []

    latest = max(
        records,
        key=lambda info: (
            info["received_at"] or "",
            info["message_id"] == "currentrecord",
        ),
    )
    if latest["dedup_key"] is not None:
        return [
            info
            for info in records
            if info["dedup_key"] == latest["dedup_key"]
        ]
    return [latest]


def _primary_record(records: Sequence[dict[str, Any]]) -> Any:
    if not records:
        return None
    latest = max(
        records,
        key=lambda info: (
            info["received_at"] or "",
            info["message_id"] == "currentrecord",
        ),
    )
    return latest["record"]


def _latest_meter_energy_wh(
    meter_values: Any,
    transaction_id: str | None,
    transaction_started_at: str | None,
    transaction_stopped_at: str | None,
) -> float | None:
    snapshot = _mapping(meter_values)
    meter_transaction_id = _optional_text(snapshot.get("transaction_id"))
    if transaction_id is None or meter_transaction_id != transaction_id:
        return None
    if not _at_or_after(
        snapshot.get("received_at"),
        _timestamp(transaction_started_at),
    ) or not _at_or_before(
        snapshot.get("received_at"),
        _timestamp(transaction_stopped_at),
    ):
        return None

    latest = None
    for entry in snapshot.get("meter_values", ()):
        for sample in _mapping(entry).get("sampled_values", ()):
            sample_mapping = _mapping(sample)
            if (
                sample_mapping.get("measurand")
                != "Energy.Active.Import.Register"
            ):
                continue
            value = _optional_float(sample_mapping.get("numeric_value"))
            if value is None:
                continue
            unit = sample_mapping.get("unit") or "Wh"
            if unit == "Wh":
                latest = value
            elif unit == "kWh":
                latest = value * 1000
    return latest


def build_unified_session(
    transaction: Mapping[str, Any] | None,
    *,
    meter_values: Mapping[str, Any] | None = None,
    session_records: Sequence[Any] = (),
    charge_point_id: str | None = None,
    source_instance_id: str | None = None,
) -> dict[str, Any] | None:
    """Build one diagnostic session view without discarding source values."""
    transaction = _mapping(transaction)
    start_snapshot = _mapping(transaction.get("start"))
    stop_snapshot = _mapping(transaction.get("stop"))
    start_request = _request(start_snapshot)
    stop_request = _request(stop_snapshot)
    transaction_id = _transaction_id(transaction)
    matching_records = _select_records(
        session_records,
        transaction_id,
        _optional_text(start_snapshot.get("received_at")),
    )
    record = _primary_record(matching_records)

    has_ocpp = bool(transaction)
    has_growatt = record is not None
    if not has_ocpp and not has_growatt:
        return None

    if has_ocpp and has_growatt:
        correlation_status = CORRELATION_MATCHED
    elif has_ocpp:
        correlation_status = CORRELATION_OCPP_ONLY
    else:
        correlation_status = CORRELATION_GROWATT_ONLY

    meter_start = _optional_float(start_request.get("meter_start"))
    meter_stop = _optional_float(stop_request.get("meter_stop"))
    meter_delta = None
    if meter_start is not None and meter_stop is not None:
        meter_delta = meter_stop - meter_start

    latest_meter_energy = _latest_meter_energy_wh(
        meter_values,
        transaction_id,
        _optional_text(start_snapshot.get("received_at")),
        _optional_text(stop_snapshot.get("received_at")),
    )
    growatt_energy = (
        _optional_float(getattr(record, "energy_wh", None))
        if record is not None
        else None
    )
    comparison_energy = meter_delta
    if comparison_energy is None:
        comparison_energy = latest_meter_energy

    record_transaction_id = (
        _optional_text(getattr(record, "transaction_id", None))
        if record is not None
        else None
    )
    connector_id = _optional_text(start_request.get("connector_id"))
    if connector_id is None and record is not None:
        connector_id = _optional_text(getattr(record, "connector_id", None))

    session_source = (
        SOURCE_HOME_ASSISTANT if has_ocpp else SOURCE_EXTERNAL_OR_UNKNOWN
    )
    if has_ocpp:
        session_started_at = (
            _optional_text(start_request.get("timestamp"))
            or _optional_text(start_snapshot.get("received_at"))
        )
        session_ended_at = (
            _optional_text(stop_request.get("timestamp"))
            or _optional_text(stop_snapshot.get("received_at"))
        )
    else:
        session_started_at = _optional_text(
            getattr(record, "start_time", None)
        )
        session_ended_at = _optional_text(
            getattr(record, "end_time", None)
        )
    session_id = build_session_id(
        source=session_source,
        source_instance_id=source_instance_id,
        charge_point_id=charge_point_id,
        transaction_id=transaction_id or record_transaction_id,
        started_at=session_started_at,
        ended_at=session_ended_at,
        record_id=(
            _optional_text(getattr(record, "record_id", None))
            if record is not None
            else None
        ),
    )

    return {
        "correlation": {
            "status": correlation_status,
            "transaction_id_match": (
                transaction_id == record_transaction_id
                if transaction_id is not None and record_transaction_id is not None
                else None
            ),
            "sources": [
                source
                for source, available in (
                    ("ocpp", has_ocpp),
                    (
                        "currentrecord",
                        any(
                            info["message_id"] == "currentrecord"
                            for info in matching_records
                        ),
                    ),
                    (
                        "frozenrecord",
                        any(
                            info["message_id"] == "frozenrecord"
                            for info in matching_records
                        ),
                    ),
                )
                if available
            ],
        },
        "identity": {
            "session_id": session_id,
            "session_source": session_source,
            "transaction_scope": session_source,
            "ocpp_transaction_id": transaction_id,
            "growatt_transaction_id": record_transaction_id,
            "connector_id": connector_id,
            "growatt_record_id": (
                _optional_text(getattr(record, "record_id", None))
                if record is not None
                else None
            ),
        },
        "timing": {
            "ocpp": {
                "start_timestamp": _optional_text(start_request.get("timestamp")),
                "start_received_at": _optional_text(
                    start_snapshot.get("received_at")
                ),
                "stop_timestamp": _optional_text(stop_request.get("timestamp")),
                "stop_received_at": _optional_text(
                    stop_snapshot.get("received_at")
                ),
            },
            "growatt": {
                "plug_time": _optional_text(
                    getattr(record, "plug_time", None)
                ),
                "start_time": _optional_text(
                    getattr(record, "start_time", None)
                ),
                "end_time": _optional_text(
                    getattr(record, "end_time", None)
                ),
                "unplug_time": _optional_text(
                    getattr(record, "unplug_time", None)
                ),
                "duration_minutes": _optional_float(
                    getattr(record, "duration_minutes", None)
                ),
            },
        },
        "metering": {
            "ocpp_meter_start_wh": meter_start,
            "ocpp_meter_stop_wh": meter_stop,
            "ocpp_meter_delta_wh": meter_delta,
            "latest_meter_value_wh": latest_meter_energy,
            "growatt_energy_wh": growatt_energy,
            "energy_delta_wh": (
                growatt_energy - comparison_energy
                if growatt_energy is not None and comparison_energy is not None
                else None
            ),
        },
        "billing": {
            "growatt_cost": (
                _optional_float(getattr(record, "cost", None))
                if record is not None
                else None
            ),
        },
        "modes": {
            "growatt_charge_mode": (
                _optional_text(getattr(record, "charge_mode", None))
                if record is not None
                else None
            ),
            "growatt_work_mode": (
                _optional_text(getattr(record, "work_mode", None))
                if record is not None
                else None
            ),
        },
        "stop_reason": _optional_text(stop_request.get("reason")),
    }
