"""Validated native THOR charging-target values and wire metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum


class TargetState(StrEnum):
    """Existing persisted target states; their wire/storage spelling is stable."""

    QUEUED = "queued"
    RESERVATION_QUEUED = "reservation_queued"
    SCHEDULED = "scheduled"
    SCHEDULED_MISSED = "scheduled_missed"
    SCHEDULED_CANCELLED = "scheduled_cancelled"
    BLOCKED_BEFORE_TARGET = "blocked_before_target"
    COMPLETED = "completed"
    TARGET_REJECTED = "target_rejected"
    TARGET_ACCEPTED_WAITING_FOR_PLUG = "target_accepted_waiting_for_plug"
    TARGET_ACCEPTED_WAITING_FOR_RFID = "target_accepted_waiting_for_rfid"
    START_ACCEPTED = "start_accepted"
    SENDING_TARGET = "sending_target"
    TARGET_ACCEPTED = "target_accepted"
    SENDING_RESERVATION = "sending_reservation"
    SENDING_START = "sending_start"
    ACTIVE = "active"
    CHARGING = "charging"
    MISSED_WHILE_UNAVAILABLE = "missed_while_unavailable"
    OUTCOME_UNKNOWN = "outcome_unknown"
    QUEUE_FAILED = "queue_failed"
    CANCELLATION_QUEUED = "cancellation_queued"
    SENDING_CANCELLATION = "sending_cancellation"
    CANCELLATION_REJECTED_RESERVATION_MAY_REMAIN = "cancellation_rejected_reservation_may_remain"
    RESERVATION_REJECTED_TARGET_MAY_REMAIN = "reservation_rejected_target_may_remain"
    START_REJECTED_TARGET_MAY_REMAIN = "start_rejected_target_may_remain"
    TARGET_ACCEPTED_RESERVATION_BLOCKED = "target_accepted_reservation_blocked"
    TARGET_ACCEPTED_START_BLOCKED = "target_accepted_start_blocked"


CAPTURE_FIRMWARE = "THOR_22AS-V2.2.16-20240902"
MESSAGE_IDS = {
    "duration": "G_SetTime",
    "energy": "G_SetEnergy",
    "budget": "G_SetAmount",
}
# Deliberate pilot bounds, not claims about the wallbox's hardware limits.
PILOT_MAXIMUM = {
    "duration": Decimal(1440),
    "energy": Decimal(100),
    "budget": Decimal(1000),
}
PILOT_MINIMUM = {
    "duration": Decimal(1),
    "energy": Decimal("0.01"),
    # Firmware V2.2.16 stopped a 0.10 attempt at 0 Wh. Whole tariff units are
    # the smallest value we expose until Growatt's decimal handling is known.
    "budget": Decimal(1),
}
NATIVE_STOP_VERIFIED = {"duration": True, "energy": True, "budget": False}


@dataclass(frozen=True, slots=True)
class ChargingTarget:
    kind: str
    value: Decimal

    @classmethod
    def parse(cls, kind: str, value: object) -> ChargingTarget:
        if kind not in MESSAGE_IDS:
            raise ValueError("unsupported_target_kind")
        text = str(value).strip().replace(",", ".")
        if not re.fullmatch(r"\d+(?:\.\d{1,2})?", text):
            raise ValueError("invalid_target_value")
        try:
            number = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError("invalid_target_value") from exc
        if not number.is_finite() or not PILOT_MINIMUM[kind] <= number <= PILOT_MAXIMUM[kind]:
            raise ValueError("target_outside_pilot_bounds")
        if kind == "duration" and number != number.to_integral_value():
            raise ValueError("duration_requires_whole_minutes")
        return cls(kind, number)

    @property
    def wire_value(self) -> str:
        value = format(self.value, "f")
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        return value.replace(".", ",") if self.kind == "budget" else value

    def payload(self) -> dict:
        return {
            "vendorId": "Growatt",
            "messageId": MESSAGE_IDS[self.kind],
            "connectorId": 1,
            "data": self.wire_value,
        }

    def diagnostic(self) -> dict:
        return {
            "kind": self.kind,
            "value": str(self.value),
            "unit": {
                "duration": "min",
                "energy": "kWh",
                "budget": "charger_tariff_units",
            }[self.kind],
        }


def target_plan(target: ChargingTarget, start: str = "now") -> dict:
    """Return the capture-backed operation plan without claiming completion."""
    if start not in {"now", "once", "recurring"}:
        raise ValueError("unsupported_start_kind")
    reservation = start == "once"
    recurring = start == "recurring"
    return {
        **target.diagnostic(),
        "start": start,
        "pilot_supported": True,
        "reason": (
            "budget_native_stop_not_verified"
            if target.kind == "budget"
            else "capture_backed_native_target"
        ),
        "target_payload": target.payload(),
        "activation": (
            "ReserveNow+target+RemoteStartTransaction"
            if reservation
            else "HA-daily-target+RemoteStartTransaction"
            if recurring
            else "target+RemoteStartTransaction"
        ),
        "automatic_stop_verified": NATIVE_STOP_VERIFIED[target.kind],
    }
