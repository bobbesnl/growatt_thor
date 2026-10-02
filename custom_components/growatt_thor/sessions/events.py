"""Session-scoped event markers for the Lovelace history chart."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from typing import Any


ACTIVE_POWER_THRESHOLD_W = 100.0
# A normal session needs only a handful of semantic anchors.  Keep enough room
# for repeated pause/resume transitions on a changeable PV day without allowing
# one unusually noisy session to dominate the Home Assistant state payload.
MAX_SESSION_EVENTS = 24

EVENT_TYPES = frozenset(
    {
        "plugged_in",
        "transaction_started",
        "energy_flow_started",
        "charging_paused",
        "energy_flow_stopped",
        "stop_requested",
        "transaction_stopped",
        "unplugged",
    }
)
EVENT_SOURCES = frozenset({"ocpp", "growatt", "meter", "home_assistant"})
EVENT_CERTAINTIES = frozenset({"observed", "derived", "provisional"})
_ANCHOR_EVENT_TYPES = frozenset(
    {
        "plugged_in",
        "transaction_started",
        "stop_requested",
        "energy_flow_stopped",
        "transaction_stopped",
        "unplugged",
    }
)


def _bounded_events(events: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep semantic anchors and evenly sample noisy transition events."""
    if len(events) <= MAX_SESSION_EVENTS:
        return events
    mandatory = {0, len(events) - 1}
    for index, event in enumerate(events):
        if event.get("type") in _ANCHOR_EVENT_TYPES:
            mandatory.add(index)
    if len(mandatory) > MAX_SESSION_EVENTS:
        ordered = sorted(mandatory)
        mandatory = {
            ordered[round(position * (len(ordered) - 1) / (MAX_SESSION_EVENTS - 1))]
            for position in range(MAX_SESSION_EVENTS)
        }
    remaining = MAX_SESSION_EVENTS - len(mandatory)
    candidates = [index for index in range(len(events)) if index not in mandatory]
    if remaining > 0 and candidates:
        if remaining >= len(candidates):
            mandatory.update(candidates)
        elif remaining == 1:
            mandatory.add(candidates[len(candidates) // 2])
        else:
            mandatory.update(
                candidates[
                    round(position * (len(candidates) - 1) / (remaining - 1))
                ]
                for position in range(remaining)
            )
    return [event for index, event in enumerate(events) if index in mandatory]


def session_event(
    event_type: object,
    at: object,
    source: object,
    certainty: object,
    *,
    reason: object | None = None,
) -> dict[str, str] | None:
    """Build one bounded, display-safe event or reject invalid input."""
    normalized_type = str(event_type)
    normalized_at = str(at).strip() if at is not None else ""
    normalized_source = str(source)
    normalized_certainty = str(certainty)
    if (
        normalized_type not in EVENT_TYPES
        or not normalized_at
        or normalized_source not in EVENT_SOURCES
        or normalized_certainty not in EVENT_CERTAINTIES
    ):
        return None
    event = {
        "type": normalized_type,
        "at": normalized_at,
        "source": normalized_source,
        "certainty": normalized_certainty,
    }
    if reason not in (None, ""):
        reason_value = reason.value if hasattr(reason, "value") else reason
        event["reason"] = str(reason_value)[:120]
    return event


def normalize_session_events(value: Any) -> list[dict[str, str]]:
    """Return only valid events and keep the frontend payload bounded."""
    result: list[dict[str, str]] = []
    for raw in value if isinstance(value, (list, tuple)) else ():
        if not isinstance(raw, dict):
            continue
        event = session_event(
            raw.get("type"),
            raw.get("at"),
            raw.get("source"),
            raw.get("certainty"),
            reason=raw.get("reason"),
        )
        if event is not None:
            result.append(event)
    return _bounded_events(result)


def append_session_event(
    events: list[dict[str, str]],
    event: dict[str, str] | None,
    *,
    unique_type: bool = False,
) -> bool:
    """Append a valid non-duplicate event and enforce the payload bound."""
    if event is None:
        return False
    if unique_type and any(item.get("type") == event["type"] for item in events):
        return False
    if any(
        item.get("type") == event["type"]
        and item.get("at") == event["at"]
        and item.get("source") == event["source"]
        for item in events
    ):
        return False
    events.append(event)
    if len(events) > MAX_SESSION_EVENTS:
        events[:] = _bounded_events(events)
    return True


def merge_growatt_record_events(
    events: Any,
    *,
    plug_time: object | None,
    start_time: object | None,
    end_time: object | None,
    unplug_time: object | None,
) -> list[dict[str, str]]:
    """Add only timestamps explicitly reported by a Growatt session record."""
    merged = normalize_session_events(events)
    for event_type, at in (
        ("plugged_in", plug_time),
        ("energy_flow_started", start_time),
        ("energy_flow_stopped", end_time),
        ("unplugged", unplug_time),
    ):
        append_session_event(
            merged,
            session_event(event_type, at, "growatt", "observed"),
            unique_type=True,
        )
    return merged


@dataclass(slots=True)
class SessionEventTracker:
    """Track honest observed and meter-derived events for one transaction."""

    events: list[dict[str, str]] = field(default_factory=list)
    energy_flowing: bool | None = None

    @classmethod
    def start(
        cls,
        at: object,
        *,
        plugged_event: dict[str, str] | None = None,
    ) -> "SessionEventTracker":
        tracker = cls()
        append_session_event(tracker.events, plugged_event, unique_type=True)
        append_session_event(
            tracker.events,
            session_event("transaction_started", at, "ocpp", "observed"),
            unique_type=True,
        )
        return tracker

    def observe_suspension(self, at: object, status: str) -> bool:
        """Record a reported pause even when the charger stops sending meters.

        This is a status observation, not a zero-watt sample or evidence that the
        battery is full. Keep the transaction open for a later charging resume.
        """
        if status not in {"suspended_ev", "suspended_evse"}:
            return False
        event = session_event("charging_paused", at, "ocpp", "observed", reason=status)
        if event is None:
            return False
        last_transition = next(
            (item for item in reversed(self.events)
             if item["type"] in {"charging_paused", "energy_flow_started"}),
            None,
        )
        self.energy_flowing = False
        if last_transition and last_transition["type"] == "charging_paused":
            if last_transition.get("certainty") == "provisional":
                # Replace the tentative meter inference with the confirmed report.
                last_transition.update(event)
                return True
            if last_transition.get("reason") == status:
                return False
        return append_session_event(self.events, event)

    def observe_power(self, at: object, watts: object) -> bool:
        """Derive flow, pause and resume transitions from total charger power."""
        try:
            power_w = float(watts)
        except (TypeError, ValueError):
            return False
        if not isfinite(power_w) or power_w < 0:
            return False
        last_transition = next(
            (item for item in reversed(self.events)
             if item["type"] in {"charging_paused", "energy_flow_started"}),
            None,
        )
        if last_transition and last_transition.get("source") == "ocpp":
            # A delayed pre-pause meter packet must not create a false resume.
            try:
                sample_at = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
                pause_at = datetime.fromisoformat(last_transition["at"].replace("Z", "+00:00"))
                if sample_at <= pause_at:
                    return False
            except (TypeError, ValueError):
                return False
        flowing = power_w > ACTIVE_POWER_THRESHOLD_W
        if self.energy_flowing is None:
            self.energy_flowing = flowing
            if not flowing:
                return False
            return append_session_event(
                self.events,
                session_event("energy_flow_started", at, "meter", "derived"),
            )
        if flowing == self.energy_flowing:
            return False

        self.energy_flowing = flowing
        if not flowing:
            return append_session_event(
                self.events,
                session_event("charging_paused", at, "meter", "provisional"),
            )

        for event in reversed(self.events):
            if (
                event.get("type") == "charging_paused"
                and event.get("certainty") == "provisional"
            ):
                event["certainty"] = "derived"
                break
        return append_session_event(
            self.events,
            session_event("energy_flow_started", at, "meter", "derived"),
        )

    def record_stop_requested(self, at: object) -> bool:
        """Record a Home Assistant stop request only once per transaction."""
        return append_session_event(
            self.events,
            session_event(
                "stop_requested",
                at,
                "home_assistant",
                "observed",
                reason="remote_stop",
            ),
            unique_type=True,
        )

    def stop(self, at: object, *, reason: object | None = None) -> None:
        """Finalize the effective stop and retain the observed OCPP stop."""
        had_energy_flow = any(
            event.get("type") == "energy_flow_started"
            for event in self.events
        )
        converted_pause = False
        if had_energy_flow and self.energy_flowing is False:
            for event in reversed(self.events):
                if event.get("type") == "energy_flow_started":
                    break
                if event.get("type") == "charging_paused":
                    if event.get("certainty") == "provisional":
                        event["type"] = "energy_flow_stopped"
                        event["certainty"] = "derived"
                    else:
                        # Preserve a confirmed pause. The later transaction stop
                        # does not mean energy continued flowing until unplugging.
                        append_session_event(
                            self.events,
                            session_event("energy_flow_stopped", event["at"], event["source"], "derived"),
                            unique_type=True,
                        )
                    converted_pause = True
                    break
        if had_energy_flow and (
            self.energy_flowing is True
            or (self.energy_flowing is False and not converted_pause)
        ):
            append_session_event(
                self.events,
                session_event("energy_flow_stopped", at, "meter", "derived"),
                unique_type=True,
            )
        append_session_event(
            self.events,
            session_event(
                "transaction_stopped",
                at,
                "ocpp",
                "observed",
                reason=reason,
            ),
            unique_type=True,
        )
        self.energy_flowing = False
