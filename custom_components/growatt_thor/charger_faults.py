"""Normalize persistent Growatt charger fault events."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from urllib.parse import unquote


CHARGER_FAULT_OPTIONS = (
    "emergency_stop",
    "power_meter_failure",
    "other_fault",
)


def _text(value: object) -> str | None:
    if hasattr(value, "value"):
        value = value.value
    if value in (None, ""):
        return None
    return str(value)


def _connector_id(value: object) -> int | str | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return text


def _token(value: object) -> str:
    return "".join(
        character
        for character in str(_text(value) or "").casefold()
        if character.isalnum()
    )


def classify_charger_fault(
    *,
    ocpp_error_code: object = None,
    growatt_error_code: object = None,
    message: object = None,
) -> str:
    """Map confirmed faults to stable Home Assistant states."""
    if _text(growatt_error_code) == "100" or "emergencystop" in _token(message):
        return "emergency_stop"
    if (
        _token(ocpp_error_code) == "powermeterfailure"
        or _token(message) == "485fault"
    ):
        return "power_meter_failure"
    return "other_fault"


@dataclass(frozen=True, slots=True)
class ChargerFault:
    """One merged OCPP/Growatt charger fault event."""

    category: str
    observed_at: str
    reported_at: str | None = None
    connector_id: int | str | None = None
    ocpp_error_code: str | None = None
    vendor_id: str | None = None
    vendor_error_code: str | None = None
    growatt_error_code: str | None = None
    message: str | None = None
    sources: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: Any) -> "ChargerFault | None":
        """Restore a fault defensively from Home Assistant storage."""
        if not isinstance(value, Mapping):
            return None
        observed_at = _text(value.get("observed_at"))
        if observed_at is None:
            return None
        category = _text(value.get("category")) or "other_fault"
        if category not in CHARGER_FAULT_OPTIONS:
            category = "other_fault"
        sources = value.get("sources")
        return cls(
            category=category,
            observed_at=observed_at,
            reported_at=_text(value.get("reported_at")),
            connector_id=_connector_id(value.get("connector_id")),
            ocpp_error_code=_text(value.get("ocpp_error_code")),
            vendor_id=_text(value.get("vendor_id")),
            vendor_error_code=_text(value.get("vendor_error_code")),
            growatt_error_code=_text(value.get("growatt_error_code")),
            message=_text(value.get("message")),
            sources=tuple(str(item) for item in sources)
            if isinstance(sources, (list, tuple))
            else (),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe persistent representation."""
        return {
            "category": self.category,
            "observed_at": self.observed_at,
            "reported_at": self.reported_at,
            "connector_id": self.connector_id,
            "ocpp_error_code": self.ocpp_error_code,
            "vendor_id": self.vendor_id,
            "vendor_error_code": self.vendor_error_code,
            "growatt_error_code": self.growatt_error_code,
            "message": self.message,
            "sources": list(self.sources),
        }


def fault_from_status_notification(
    observed_at: str,
    connector_id: object,
    error_code: object,
    payload: Mapping[str, Any],
) -> ChargerFault:
    """Build a fault from an OCPP Faulted StatusNotification."""
    message = _text(payload.get("info")) or _text(payload.get("vendor_error_code"))
    ocpp_error_code = _text(error_code)
    return ChargerFault(
        category=classify_charger_fault(
            ocpp_error_code=ocpp_error_code,
            message=message,
        ),
        observed_at=observed_at,
        connector_id=_connector_id(connector_id),
        ocpp_error_code=ocpp_error_code,
        vendor_id=_text(payload.get("vendor_id")),
        vendor_error_code=_text(payload.get("vendor_error_code")),
        message=message,
        sources=("StatusNotification",),
    )


def _events_are_close(first: str, second: str) -> bool:
    try:
        return abs(
            (datetime.fromisoformat(first) - datetime.fromisoformat(second)).total_seconds()
        ) <= 30
    except (TypeError, ValueError):
        return False


def fault_from_data_transfer(
    observed_at: str,
    vendor_id: object,
    data: str,
    existing: ChargerFault | None = None,
) -> ChargerFault:
    """Parse and, when possible, merge Growatt DataTransfer/faultmessage."""
    if not isinstance(data, str):
        raise TypeError("faultmessage payload must be a string")
    values = {}
    for field in data.split("&"):
        key, separator, value = field.partition("=")
        if separator:
            # Growatt sends a query-like string without URL-encoding its '+'
            # timezone offset, so unquote is correct here rather than parse_qsl.
            values[unquote(key)] = unquote(value)
    connector_id = _connector_id(values.get("connectorId"))
    growatt_error_code = _text(values.get("errcode"))
    message = _text(values.get("info"))
    category = classify_charger_fault(
        growatt_error_code=growatt_error_code,
        message=message,
    )
    can_merge = (
        existing is not None
        and existing.connector_id == connector_id
        and existing.category == category
        and _events_are_close(existing.observed_at, observed_at)
    )
    if can_merge:
        sources = tuple(dict.fromkeys((*existing.sources, "DataTransfer/faultmessage")))
        return replace(
            existing,
            reported_at=_text(values.get("time")) or existing.reported_at,
            vendor_id=_text(vendor_id) or existing.vendor_id,
            growatt_error_code=growatt_error_code or existing.growatt_error_code,
            message=message or existing.message,
            sources=sources,
        )
    return ChargerFault(
        category=category,
        observed_at=observed_at,
        reported_at=_text(values.get("time")),
        connector_id=connector_id,
        vendor_id=_text(vendor_id),
        growatt_error_code=growatt_error_code,
        message=message,
        sources=("DataTransfer/faultmessage",),
    )
