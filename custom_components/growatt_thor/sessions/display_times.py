"""Normalize only the presentation of retained sessions, preserving raw identities."""

from __future__ import annotations

from ..ocpp.meter_samples import meter_time_zone
from ..timestamps import installation_time_zone, utc_timestamp


def session_time_zone(coordinator):
    """Use the same verified wallbox clock for session and meter timestamps."""
    return meter_time_zone(
        getattr(coordinator, "configuration_values", {}),
        installation_time_zone(getattr(coordinator, "hass", None)),
    )


_CURVES = (
    "power_curve",
    "measured_current_sum_curve_a",
    "configured_current_limit_curve_a",
    "site_pv_surplus_curve_w",
    "site_house_load_curve_w",
    "site_battery_curve_w",
)


def session_times(item: dict, time_zone: str) -> dict:
    result = dict(item)
    for key in ("start_time", "end_time"):
        if key in result:
            result[key] = utc_timestamp(result[key], time_zone)
    for key in _CURVES:
        if key in result:
            result[key] = [
                [at, point[1]]
                for point in result[key]
                if (at := utc_timestamp(point[0], time_zone)) is not None
            ]
    if "events" in result:
        result["events"] = [
            {**event, "at": at}
            for event in result["events"]
            if (at := utc_timestamp(event.get("at"), time_zone)) is not None
        ]
    return result
