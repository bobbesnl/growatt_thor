"""Redacted ring buffer of the latest OCPP frames for diagnostics.

The buffer holds only memory: a restart or reload starts empty. The coordinator
owns one per entry, so frames from before a reconnect stay visible next to the
frames of the replacement connection.

Every payload passes the same redaction as the other diagnostics sections:
identifiers by field name, configuration values by the registry's sensitivity
and Growatt DataTransfer data, which can carry card numbers in session records.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Mapping
from typing import Any, Literal

from ...configuration.values import redact_configuration_value
from ..core.diagnostics import REDACTED, redact_ocpp_data

OCPP_MESSAGE_LOG_CAPACITY = 50

#: DataTransfer exchanges whose data is meter readings without identifiers.
_PUBLIC_DATA_TRANSFER_MESSAGE_IDS = frozenset({"get_external_meterval"})

_CALL, _CALL_RESULT, _CALL_ERROR = 2, 3, 4
_MESSAGE_TYPES = {_CALL: "Call", _CALL_RESULT: "CallResult", _CALL_ERROR: "CallError"}

Direction = Literal["in", "out"]


class OcppMessageLog:
    """The latest OCPP frames of one entry, oldest first."""

    __slots__ = ("_frames", "_pending_calls")

    def __init__(self, capacity: int = OCPP_MESSAGE_LOG_CAPACITY) -> None:
        self._frames: deque[dict[str, Any]] = deque(maxlen=capacity)
        # (direction of the CALL, unique id) -> (action, DataTransfer messageId).
        # Bounded like the frames: a CALL that never gets an answer must not
        # keep memory alive for the lifetime of the entry.
        self._pending_calls: dict[tuple[Direction, str], tuple[str, str | None]] = {}

    @property
    def capacity(self) -> int:
        return self._frames.maxlen or 0

    def record(self, direction: Direction, raw: str | bytes, at: str) -> None:
        """Store one frame; malformed frames are kept without payload."""
        size = len(raw) if isinstance(raw, bytes) else len(raw.encode("utf-8"))
        frame: dict[str, Any] = {
            "at": at,
            "direction": direction,
            "message_type": "Invalid",
            "action": None,
            "unique_id": None,
            "size": size,
            "payload": None,
        }
        try:
            message = json.loads(raw)
        except (TypeError, ValueError):
            message = None
        if (
            isinstance(message, list)
            and len(message) >= 3
            and message[0] in _MESSAGE_TYPES
            and isinstance(message[1], str)
        ):
            try:
                frame.update(self._describe(direction, message))
            except Exception:  # noqa: BLE001
                # Diagnostics boundary: a frame the log cannot describe must
                # not keep the OCPP router from answering it.
                frame["message_type"] = "Invalid"
        self._frames.append(frame)

    def _describe(self, direction: Direction, message: list[Any]) -> dict[str, Any]:
        message_type, unique_id = message[0], message[1]
        action: str | None
        message_id: object
        if message_type == _CALL:
            action = str(message[2])
            payload = message[3] if len(message) > 3 else None
            message_id = payload.get("messageId") if isinstance(payload, Mapping) else None
            self._remember_call(
                direction, unique_id, action, message_id if isinstance(message_id, str) else None
            )
            redacted = _redact_call(action, payload)
        else:
            # The answer travels in the opposite direction of its CALL.
            call_direction: Direction = "out" if direction == "in" else "in"
            action, message_id = self._pending_calls.pop((call_direction, unique_id), (None, None))
            if message_type == _CALL_RESULT:
                redacted = _redact_call_result(action, message_id, message[2])
            else:
                redacted = {
                    "errorCode": message[2],
                    "errorDescription": REDACTED if len(message) > 3 and message[3] else "",
                    "errorDetails": REDACTED if len(message) > 4 and message[4] else {},
                }
        return {
            "message_type": _MESSAGE_TYPES[message_type],
            "action": action,
            "unique_id": unique_id,
            "payload": redacted,
        }

    def _remember_call(
        self, direction: Direction, unique_id: str, action: str, message_id: str | None
    ) -> None:
        self._pending_calls[(direction, unique_id)] = (action, message_id)
        while len(self._pending_calls) > self.capacity:
            del self._pending_calls[next(iter(self._pending_calls))]

    def diagnostics(self) -> dict[str, Any]:
        return {"capacity": self.capacity, "messages": list(self._frames)}


def _redact_call(action: str, payload: Any) -> Any:
    if not isinstance(payload, Mapping):
        return redact_ocpp_data(payload)
    payload = dict(payload)
    if action == "ChangeConfiguration" and "value" in payload:
        payload["value"] = redact_configuration_value(payload.get("key"), payload["value"])
    elif action == "DataTransfer":
        payload = _redact_data_transfer(payload, payload.get("messageId"))
    return redact_ocpp_data(payload)


def _redact_call_result(action: str | None, message_id: object, payload: Any) -> Any:
    if not isinstance(payload, Mapping):
        return redact_ocpp_data(payload)
    payload = dict(payload)
    # An answer whose CALL dropped out of the log gets every rule.
    if action in {"GetConfiguration", None} and isinstance(payload.get("configurationKey"), list):
        payload["configurationKey"] = [
            {**item, "value": redact_configuration_value(item.get("key"), item["value"])}
            if isinstance(item, Mapping) and "value" in item
            else item
            for item in payload["configurationKey"]
        ]
    if action in {"DataTransfer", None}:
        payload = _redact_data_transfer(payload, message_id)
    return redact_ocpp_data(payload)


def _redact_data_transfer(payload: dict[str, Any], message_id: object) -> dict[str, Any]:
    if payload.get("data") not in (None, "") and message_id not in (
        _PUBLIC_DATA_TRANSFER_MESSAGE_IDS
    ):
        payload["data"] = REDACTED
    return payload
