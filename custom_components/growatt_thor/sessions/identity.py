"""Stable source-aware identities for charging sessions."""
from __future__ import annotations

import hashlib
import json
from typing import Any


SOURCE_HOME_ASSISTANT = "home_assistant"
SOURCE_EXTERNAL_OR_UNKNOWN = "external_or_unknown"
SOURCE_LEGACY_UNKNOWN = "legacy_unknown"

_SOURCE_PREFIXES = {
    SOURCE_HOME_ASSISTANT: "ha",
    SOURCE_EXTERNAL_OR_UNKNOWN: "ext",
    SOURCE_LEGACY_UNKNOWN: "legacy",
}


def _text(value: Any) -> str:
    return "" if value in (None, "") else str(value)


def normalize_session_source(value: Any) -> str:
    """Return a supported source label without inventing provenance."""
    source = _text(value)
    if source in _SOURCE_PREFIXES:
        return source
    return SOURCE_EXTERNAL_OR_UNKNOWN


def build_session_id(
    *,
    source: str,
    source_instance_id: Any = None,
    charge_point_id: Any = None,
    transaction_id: Any = None,
    started_at: Any = None,
    ended_at: Any = None,
    record_id: Any = None,
) -> str:
    """Build a compact deterministic ID while retaining source separately."""
    normalized_source = normalize_session_source(source)
    normalized_start = _text(started_at)
    normalized_end = _text(ended_at)
    normalized_record_id = _text(record_id)
    if normalized_source == SOURCE_HOME_ASSISTANT:
        normalized_end = ""
        normalized_record_id = ""
    elif normalized_start:
        normalized_end = ""
        normalized_record_id = ""
    elif normalized_end:
        normalized_record_id = ""

    identity = {
        "source": normalized_source,
        "source_instance_id": (
            _text(source_instance_id)
            if normalized_source == SOURCE_HOME_ASSISTANT
            else ""
        ),
        "charge_point_id": _text(charge_point_id),
        "transaction_id": _text(transaction_id),
        "started_at": normalized_start,
        "ended_at": normalized_end,
        "record_id": normalized_record_id,
    }
    canonical = json.dumps(
        identity,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{_SOURCE_PREFIXES[normalized_source]}-{digest}"
