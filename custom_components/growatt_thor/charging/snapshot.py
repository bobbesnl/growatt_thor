"""Immutable, derived view of one charger's live state.

Entities, the card and automatic controls read connection, OCPP status,
transaction and the latest meter reading through this snapshot instead of
combining coordinator attributes themselves. The snapshot only derives; it
never changes the observations it is built from. The raw OCPP status stays
available next to the normalized status and the derived vehicle state.

Freshness is explicit: the meter reading carries the time THOR sampled it and
the time the integration received it, and ``meter_stale_after_s`` says how old
both may become before the reading no longer counts as live.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from ..coerce import enum_value
from ..energy.meter_observations import ChargingMeterObservation, charging_meter_values
from ..ocpp.status import normalize_ocpp_status


class VehicleState(StrEnum):
    """Vehicle state in the style of IEC 61851, derived from OCPP observations."""

    DISCONNECTED = "disconnected"  # A: no vehicle
    CONNECTED = "connected"  # B: vehicle plugged in, not drawing energy
    CHARGING = "charging"  # C: energy flows
    FAULT = "fault"  # E/F: the charger reports a fault
    UNKNOWN = "unknown"  # no connection, no status or an ambiguous status


# Reserved, Unavailable and the local Idle say nothing reliable about a
# plugged-in vehicle, so they stay unknown instead of being guessed.
_VEHICLE_STATES = {
    "available": VehicleState.DISCONNECTED,
    "preparing": VehicleState.CONNECTED,
    "suspended_ev": VehicleState.CONNECTED,
    "suspended_evse": VehicleState.CONNECTED,
    "finishing": VehicleState.CONNECTED,
    "charging": VehicleState.CHARGING,
    "faulted": VehicleState.FAULT,
}


@dataclass(frozen=True, slots=True)
class MeterReading:
    """Power and currents of the latest MeterValues packet.

    Values come from the packet's last entry only; an older packet is never
    blended in, and a missing value stays ``None`` instead of zero.
    """

    transaction_id: int | str | None = None
    received_at: str | None = None
    sample_at: str | None = None
    power_w: float | None = None
    currents_a: tuple[float | None, float | None, float | None] = (None, None, None)

    @classmethod
    def from_packet(cls, packet: Mapping[str, Any] | None) -> MeterReading:
        meter = charging_meter_values(packet)
        currents = meter["currents_a"]
        return cls(
            transaction_id=packet.get("transaction_id") if packet else None,
            received_at=packet.get("received_at") if packet else None,
            sample_at=meter["sample_at"],
            power_w=meter["power_w"],
            currents_a=(currents[0], currents[1], currents[2]),
        )

    def as_observation(self) -> ChargingMeterObservation:
        """Return the wire form used by the card and live allocation."""
        return {
            "power_w": self.power_w,
            "currents_a": list(self.currents_a),
            "sample_at": self.sample_at,
        }


@dataclass(frozen=True, slots=True)
class ChargerSnapshot:
    """Connection, OCPP status, transaction and latest meter reading."""

    connected: bool
    ocpp_status: str | None
    status: str | None
    transaction_id: int | str | None
    transaction_active: bool
    meter: MeterReading
    meter_stale_after_s: float

    @property
    def faulted(self) -> bool:
        return self.status == "faulted"

    @property
    def vehicle_state(self) -> VehicleState:
        if not self.connected or self.status is None:
            return VehicleState.UNKNOWN
        return _VEHICLE_STATES.get(self.status, VehicleState.UNKNOWN)

    def live_meter(self) -> MeterReading:
        """Return the reading as shown live: zero unless the charger is charging.

        The raw reading stays unchanged. A sample that arrives after charging
        ended must not show the last charging power as current; an unknown
        status does not zero the reading.
        """
        if self.connected and self.status in (None, "charging"):
            return self.meter
        return MeterReading(
            transaction_id=self.meter.transaction_id,
            received_at=self.meter.received_at,
            sample_at=self.meter.sample_at,
            power_w=0,
            currents_a=(0, 0, 0),
        )


class ChargerStateOwner(Protocol):
    connected: bool
    status: str | None
    transaction_id: int | str | None
    last_meter_values: dict[str, Any] | None

    @property
    def transaction_is_active(self) -> bool: ...

    @property
    def effective_meter_gap_seconds(self) -> float: ...


def charger_snapshot(owner: ChargerStateOwner) -> ChargerSnapshot:
    """Derive the current snapshot from the owner's retained observations."""
    status = owner.status
    return ChargerSnapshot(
        connected=bool(owner.connected),
        ocpp_status=(
            str(enum_value(status, stringify_fallback=True)) if status is not None else None
        ),
        status=normalize_ocpp_status(status),
        transaction_id=owner.transaction_id,
        transaction_active=bool(owner.transaction_is_active),
        meter=MeterReading.from_packet(owner.last_meter_values),
        meter_stale_after_s=owner.effective_meter_gap_seconds,
    )
