"""Live source allocation using the same site-input policy as session accounting."""

from collections.abc import Mapping
from datetime import timedelta
from typing import TypedDict

from ..timestamps import parse_utc as parse_at
from .allocation import EVEnergyDelta, allocate
from .contracts import LiveAllocationOwner
from .meter_observations import ChargingMeterObservation
from .site_inputs import site_inputs

WATT_SECONDS_PER_KWH = 3_600_000


class ChargingSources(TypedDict):
    solar_w: float
    grid_w: float
    battery_w: float
    unknown_w: float


def live_charging_sources(
    coordinator: LiveAllocationOwner,
    meter_display: ChargingMeterObservation,
    snapshot: Mapping[str, object],
) -> ChargingSources | None:
    charging_sources: ChargingSources | None = None
    sample_at = parse_at(meter_display.get("sample_at"))
    received_at = parse_at(snapshot.get("received_at"))
    now = parse_at(coordinator.now())
    power_w = meter_display.get("power_w")
    if (
        sample_at is not None
        and received_at is not None
        and now is not None
        and power_w is not None
        and power_w >= 0
        and 0 <= (now - sample_at).total_seconds() <= coordinator.effective_meter_gap_seconds()
        and 0 <= (now - received_at).total_seconds() <= coordinator.effective_meter_gap_seconds()
        and coordinator.transaction_is_active
    ):
        # Live sources have independent update schedules; evaluate them now,
        # after checking the charger's sample and receipt are both still fresh.
        inputs = site_inputs(coordinator, now)
        if inputs is not None:
            live = allocate(
                EVEnergyDelta(
                    coordinator.source_instance_id or "site",
                    coordinator.charge_point_id or "charger",
                    str(coordinator.transaction_id),
                    now - timedelta(seconds=1),
                    now,
                    power_w / WATT_SECONDS_PER_KWH,
                ),
                *inputs,
            )
            charging_sources = {
                "solar_w": live.direct_solar * WATT_SECONDS_PER_KWH,
                "grid_w": live.direct_grid * WATT_SECONDS_PER_KWH,
                "battery_w": live.battery_unknown * WATT_SECONDS_PER_KWH,
                "unknown_w": 0.0,
            }
            charging_sources["unknown_w"] = max(
                0.0,
                power_w - sum(charging_sources[key] for key in ("solar_w", "grid_w", "battery_w")),
            )
    return charging_sources
