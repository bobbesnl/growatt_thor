"""Home Assistant events for automations, with a stable payload per event type.

Each event carries the charger's ``device_id`` and ``config_entry_id`` (added by
the publisher that setup connects) next to the fields below. Field names and
values are a public contract: add fields, never rename or remove them.

Publication is secondary to the observation that triggers it. The publisher
runs after the state change is complete, and a failure is logged instead of
reaching the command queue, an OCPP handler or the target runtime. Until setup
connects a publisher, events are dropped, so restored state never fires one.

No payload contains an RFID tag: session events identify the session by its
transaction ID only.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from ..charging.faults import ChargerFault
    from .write_results import ChargerCommandResult

_LOGGER = logging.getLogger(__name__)

EVENT_COMMAND_RESULT: Final = "growatt_thor_command_result"
EVENT_SESSION_STARTED: Final = "growatt_thor_session_started"
EVENT_SESSION_COMPLETED: Final = "growatt_thor_session_completed"
EVENT_TARGET_STATE_CHANGED: Final = "growatt_thor_target_state_changed"
EVENT_FAULT: Final = "growatt_thor_fault"

#: Device trigger type -> event type. Trigger types are translation keys.
DEVICE_TRIGGER_EVENTS: Final = {
    "command_result": EVENT_COMMAND_RESULT,
    "session_started": EVENT_SESSION_STARTED,
    "session_completed": EVENT_SESSION_COMPLETED,
    "target_state_changed": EVENT_TARGET_STATE_CHANGED,
    "charger_fault": EVENT_FAULT,
}

EventPublisher = Callable[[str, dict[str, Any]], None]


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class AutomationEvents:
    """Build and publish the automation events of one entry."""

    __slots__ = ("_publish",)

    def __init__(self) -> None:
        self._publish: EventPublisher | None = None

    @property
    def connected(self) -> bool:
        return self._publish is not None

    def connect(self, publish: EventPublisher | None) -> None:
        """Attach the HA publisher; ``None`` stops publication on unload."""
        self._publish = publish

    def _fire(self, event_type: str, data: dict[str, Any]) -> None:
        if self._publish is None:
            return
        try:
            self._publish(event_type, data)
        except Exception:
            # Event publication boundary: the observation is already complete.
            _LOGGER.exception("Failed to publish %s", event_type)

    def command_result(self, result: ChargerCommandResult) -> None:
        self._fire(EVENT_COMMAND_RESULT, dict(result.as_dict()))

    def session_started(
        self,
        *,
        transaction_id: int | str,
        connector_id: object,
        meter_start: object,
        started_at: str | None,
    ) -> None:
        self._fire(
            EVENT_SESSION_STARTED,
            {
                "transaction_id": transaction_id,
                "connector_id": connector_id,
                "meter_start_wh": _number(meter_start),
                "started_at": started_at,
            },
        )

    def session_completed(
        self,
        completed: Mapping[str, Any],
        *,
        transaction_id: int | str | None,
        reason: str | None,
        meter_stop: object,
    ) -> None:
        start = completed.get("start")
        request = start.get("request") if isinstance(start, Mapping) else None
        meter_start_wh = _number(request.get("meter_start")) if request else None
        meter_stop_wh = _number(meter_stop)
        stop = completed.get("stop")
        self._fire(
            EVENT_SESSION_COMPLETED,
            {
                "transaction_id": transaction_id,
                "reason": reason,
                "meter_start_wh": meter_start_wh,
                "meter_stop_wh": meter_stop_wh,
                # Energy measured by the charger's OCPP meter; the Growatt
                # session record with cost arrives separately afterwards.
                "energy_kwh": (
                    round((meter_stop_wh - meter_start_wh) / 1000, 3)
                    if meter_start_wh is not None
                    and meter_stop_wh is not None
                    and meter_stop_wh >= meter_start_wh
                    else None
                ),
                "effective_charging_duration_minutes": completed.get(
                    "effective_charging_duration_minutes"
                ),
                "stopped_at": stop.get("received_at") if isinstance(stop, Mapping) else None,
            },
        )

    def target_state_changed(
        self,
        previous: Mapping[str, Any] | None,
        current: Mapping[str, Any] | None,
    ) -> None:
        """Fire when the persisted target state or request changes.

        ``previous_state`` belongs to the same request; a new request starts
        with ``None``. Clearing the target reports ``state: None``.
        """
        previous_id = previous.get("request_id") if previous else None
        request_id = current.get("request_id") if current else previous_id
        state = current.get("state") if current else None
        previous_state = (
            previous.get("state") if previous is not None and previous_id == request_id else None
        )
        if request_id is None or (previous_id == request_id and previous_state == state):
            return
        self._fire(
            EVENT_TARGET_STATE_CHANGED,
            {
                "request_id": request_id,
                "state": None if state is None else str(state),
                "previous_state": None if previous_state is None else str(previous_state),
            },
        )

    def fault(self, fault: ChargerFault) -> None:
        self._fire(
            EVENT_FAULT,
            {
                "category": fault.category,
                "ocpp_error_code": fault.ocpp_error_code,
                "connector_id": fault.connector_id,
                "observed_at": fault.observed_at,
            },
        )
