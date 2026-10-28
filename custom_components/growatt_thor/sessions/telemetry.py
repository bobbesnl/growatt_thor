"""Bounded session context histories, independent of source-energy accounting."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from math import isfinite

from ..configuration.values import configuration_numeric_value
from ..energy.meter_observations import charging_meter_values
from ..energy.observations import read_site_observations
from ..runtime.time import parse_utc as parse_at
from ..runtime.time import utc_timestamp
from .series import SESSION_CURVE_POINT_LIMIT, downsample_curve

CONTEXT_CURVES = (
    "measured_current_sum_curve_a",
    "configured_current_limit_curve_a",
    "site_pv_surplus_curve_w",
    "site_house_load_curve_w",
    "site_battery_curve_w",
)


def context_curves(value, *, limit=SESSION_CURVE_POINT_LIMIT, event_times=()):
    source = value if isinstance(value, Mapping) else {}
    event_times = tuple(event_times)
    return {
        key: curve
        for key in CONTEXT_CURVES
        if (
            curve := downsample_curve(
                source.get(key),
                limit=limit,
                event_times=event_times,
                signed=key == "site_battery_curve_w",
                gaps=True,
            )
        )
        and any(point[1] is not None for point in curve)
    }


class SessionTelemetry:
    def __init__(self, value=None):
        self.curves = context_curves(value)
        self.house_load_source = (
            (value or {}).get("site_house_load_source") if isinstance(value, Mapping) else None
        )
        if self.house_load_source not in ("configured_sensor", "site_balance", "mixed"):
            self.house_load_source = None

    def observe(self, key, at, value):
        timestamp = utc_timestamp(at)
        if key not in CONTEXT_CURVES or timestamp is None:
            return False
        if value is not None:
            if not isinstance(value, (int, float)) or not isfinite(value):
                return False
            if value < 0 and key != "site_battery_curve_w":
                return False
        points = self.curves.setdefault(key, [])
        if points and parse_at(timestamp) < parse_at(points[-1][0]):
            return False
        if points and timestamp == points[-1][0]:
            if points[-1][1] == value:
                return False
            points[-1] = [timestamp, value]
        elif value is None and (not points or points[-1][1] is None):
            return False
        else:
            points.append([timestamp, value])
        if len(points) > SESSION_CURVE_POINT_LIMIT * 2:
            self.curves[key] = downsample_curve(
                points, signed=key == "site_battery_curve_w", gaps=True
            )
        return True

    def snapshot(self, *, event_times=()):
        return context_curves(self.curves, event_times=event_times)

    def metadata(self):
        return {"site_house_load_source": self.house_load_source} if self.house_load_source else {}

    def observe_context(self, coordinator, at):
        site = read_site_observations(coordinator, require_recent_report=False)
        instant = parse_at(at)
        if instant is None:
            return False

        def value(observation):
            return observation.value_at(instant) if observation is not None else None

        solar, house, battery = (
            value(site.solar),
            value(site.household),
            value(site.battery),
        )
        if solar is not None and solar < 0:
            solar = None
        if house is not None and house < 0:
            house = None
        options = getattr(coordinator, "site_accounting_options", {})
        source = "configured_sensor" if house is not None else None
        if not options.get("site_house_power_entity") and solar is not None:
            snapshot = getattr(coordinator, "last_meter_values", None) or {}
            meter = charging_meter_values(snapshot)
            sampled = parse_at(meter.get("sample_at"))
            ev = meter.get("power_w")
            if str(getattr(coordinator, "status", "")).lower() in {
                "suspended_ev",
                "suspended_evse",
                "suspendedev",
                "suspendedevse",
                "finishing",
            }:
                ev = 0.0
            elif (
                sampled is None
                or not 0
                <= (instant - sampled).total_seconds()
                <= coordinator._effective_meter_gap_seconds()
            ):
                ev = None
            grid = value(site.grid)
            # Battery absence is known only for a declared battery-free topology.
            battery_balance = (
                battery
                if getattr(coordinator, "battery_power_entity", None)
                else (
                    0.0 if options.get("site_accounting_profile") in ("pv", "grid_only") else None
                )
            )
            if all(reading is not None for reading in (grid, battery_balance, ev)):
                balance = solar + grid + battery_balance - ev
                if balance >= 0:
                    house, source = balance, "site_balance"
        if source is not None:
            if self.house_load_source is not None and self.house_load_source != source:
                self.house_load_source = "mixed"
            else:
                self.house_load_source = source
        limit = configuration_numeric_value(
            getattr(coordinator, "configuration_values", {}).get("G_MaxCurrent")
        )
        values = {
            "site_house_load_curve_w": house,
            "site_pv_surplus_curve_w": max(0, solar - house)
            if solar is not None and house is not None
            else None,
            "site_battery_curve_w": battery,
            "configured_current_limit_curve_a": limit,
        }
        changed = False
        for key, reading in values.items():
            changed = self.observe(key, at, reading) or changed
        return changed

    def observe_meter(self, entry, received_at, max_age):
        sampled, received = parse_at(entry.timestamp), parse_at(received_at)
        if (
            sampled is None
            or received is None
            or not 0 <= (received - sampled).total_seconds() <= max_age
        ):
            return False
        currents = charging_meter_values({"meter_values": [entry.as_dict()]})["currents_a"]
        amps = sum(currents) if all(value is not None for value in currents) else None
        return self.observe("measured_current_sum_curve_a", entry.timestamp, amps)


def async_setup_session_history(hass, coordinator):
    """Observe configured HA sources immediately and snapshot pauses every 30s."""
    from homeassistant.helpers.event import async_track_time_interval

    async def capture(_event):
        coordinator.sessions.observe_context()

    async def state_changed(event):
        options = coordinator.site_accounting_options
        sources = {
            options.get(key)
            for key in (
                "site_solar_power_entity",
                "site_house_power_entity",
                "site_grid_power_entity",
            )
        }
        sources.add(coordinator.battery_power_entity)
        sources.discard(None)
        if event.data.get("entity_id") in sources:
            coordinator.sessions.observe_context()

    unsubscribe = hass.bus.async_listen("state_changed", state_changed)
    try:
        cancel_timer = async_track_time_interval(hass, capture, timedelta(seconds=30))
    except BaseException:
        unsubscribe()
        raise

    def stop():
        unsubscribe()
        cancel_timer()

    return stop
