"""Normalize and redact retained OCPP request snapshots."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from enum import Enum
from typing import Any


REDACTED = "<redacted>"

_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "chargeboxserialnumber",
        "chargepointserialnumber",
        "iccid",
        "idtag",
        "imsi",
        "meterserialnumber",
        "parentidtag",
    }
)


def normalize_ocpp_value(value: Any) -> Any:
    """Convert an OCPP handler value into a JSON-serializable value."""
    if isinstance(value, Enum):
        return normalize_ocpp_value(value.value)
    if isinstance(value, Mapping):
        return {
            str(key): normalize_ocpp_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [normalize_ocpp_value(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def create_ocpp_snapshot(received_at: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Create a timestamped, lossless snapshot from a routed OCPP request."""
    return {
        "received_at": received_at,
        "request": normalize_ocpp_value(payload),
    }


def boot_notification_field(
    snapshot: Mapping[str, Any] | None,
    field: str,
) -> str | None:
    """Return one non-empty field from a retained BootNotification request."""
    if not isinstance(snapshot, Mapping):
        return None

    request = snapshot.get("request")
    if not isinstance(request, Mapping):
        return None

    value = request.get(field)
    if value is None:
        return None

    normalized = str(value).strip()
    return normalized or None


def redact_ocpp_data(value: Any) -> Any:
    """Redact identifiers while preserving the OCPP diagnostics structure."""
    if isinstance(value, Mapping):
        redacted = {}
        for key, item in value.items():
            normalized_key = "".join(
                character
                for character in str(key).casefold()
                if character.isalnum()
            )
            redacted[str(key)] = (
                REDACTED
                if normalized_key in _SENSITIVE_FIELD_NAMES and item is not None
                else redact_ocpp_data(item)
            )
        return redacted
    if isinstance(value, list):
        return [redact_ocpp_data(item) for item in value]
    return value
