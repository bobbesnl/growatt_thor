"""Small, display-safe dashboard view of retained charger observations.

Use the latest MeterValues packet, not the accumulated sensor dictionaries:
otherwise an omitted phase can incorrectly look active from an earlier packet.
Only the identifier observed for a session is exposed; authorisation policy,
configured allowlists, raw packets and credentials remain private.
"""
from __future__ import annotations

from collections.abc import Mapping
import json
import logging
from math import isfinite

from ..energy.meter_observations import charging_meter_values as dashboard_meter_values
from ..charging.controls import selected_working_mode
from ..charging.limits import charging_power_identity, maximum_charging_current
from ..configuration.values import configuration_entity_state
from ..energy.sources import battery_power_attributes
from ..energy.accounting import EVEnergyDelta, allocate
from ..energy.accounting_runtime import parse_at, site_inputs
from datetime import datetime, timedelta, timezone
from ..ocpp.diagnostics import boot_notification_field
from ..sessions.identity import SOURCE_HOME_ASSISTANT, build_session_id
from ..sessions.events import normalize_session_events
from ..sessions.series import SESSION_CURVE_POINT_LIMIT, downsample_curve


_LOGGER = logging.getLogger(__name__)
DASHBOARD_SESSION_LIMIT = 20
# HA state updates carry this projection repeatedly. Full history belongs in
# CSV/WebSocket detail; increasing this budget also increases recorder traffic.
CARD_ATTRIBUTE_TARGET_BYTES = 12 * 1024
_SESSION_DETAIL_FIELDS = (
    "power_curve",
    "events",
    "measured_current_sum_curve_a",
    "configured_current_limit_curve_a",
    "site_pv_surplus_curve_w",
    "site_house_load_curve_w",
    "site_battery_curve_w",
)


def _number(value):
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if isfinite(result) and result >= 0 else None


def _signed_number(value):
    """Return a finite signed number, preserving grid import/export direction."""
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if isfinite(result) else None


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _text(value):
    return None if value in (None, "") else str(value)


def _dashboard_power_curve(value, *, event_times=()):
    """Return bounded, valid time/power pairs from the active transaction."""
    result = []
    for raw in value if isinstance(value, (list, tuple)) else ():
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            continue
        timestamp = _text(raw[0])
        watts = _number(raw[1])
        if timestamp is not None and watts is not None:
            result.append([timestamp, watts])
    return downsample_curve(
        result,
        limit=SESSION_CURVE_POINT_LIMIT,
        event_times=event_times,
    )


def dashboard_active_session(coordinator):
    """Build the transient row for the transaction currently in progress."""
    if not bool(getattr(coordinator, "transaction_is_active", False)):
        return None

    transaction = _mapping(getattr(coordinator, "active_transaction", None))
    start = _mapping(transaction.get("start"))
    request = _mapping(start.get("request"))
    response = _mapping(start.get("response"))
    transaction_id = _text(
        getattr(coordinator, "transaction_id", None)
        or response.get("transaction_id")
    )
    start_time = _text(request.get("timestamp") or start.get("received_at"))
    energy_wh = _number(getattr(coordinator, "energy", None))
    events = normalize_session_events(transaction.get("events"))
    accounting = getattr(coordinator, "site_accounting", None)
    metered_kwh = sum(accounting.buckets.values()) if accounting is not None else None
    fallback_kwh = getattr(accounting, "power_fallback_kwh", 0.0) if accounting is not None else 0.0
    return {
        "session_id": build_session_id(
            source=SOURCE_HOME_ASSISTANT,
            source_instance_id=getattr(coordinator, "source_instance_id", None),
            charge_point_id=getattr(coordinator, "charge_point_id", None),
            transaction_id=transaction_id,
            started_at=start_time,
        ),
        "active": True,
        "start_time": start_time,
        "end_time": None,
        "energy_kwh": (
            metered_kwh if metered_kwh is not None and metered_kwh > 0
            else fallback_kwh if fallback_kwh > 0
            else 0.0 if accounting is not None
            else energy_wh / 1000 if energy_wh is not None else None
        ),
        "energy_source": (
            "ocpp_meter" if metered_kwh is not None and metered_kwh > 0
            else "power_fallback" if fallback_kwh > 0 else None
        ),
        "green_energy_kwh": None,
        **(accounting.as_session_dict() if metered_kwh is not None and metered_kwh > 0 else {}),
        # Growatt reports the authoritative cost only with the completed record.
        "cost": None,
        "duration_minutes": None,
        "authorized_identifier": _text(
            request.get("id_tag") or getattr(coordinator, "id_tag", None)
        ),
        "power_curve": _dashboard_power_curve(
            getattr(coordinator, "_active_power_curve", None),
            event_times=(event.get("at") for event in events),
        ),
        "events": events,
        "detail_available": True,
    }


def dashboard_sessions(coordinator):
    """Combine bounded completed history with one optional active row."""
    history = dict(getattr(coordinator, "dashboard_sessions", {}) or {})
    items = [
        dict(item) if isinstance(item, Mapping) else item
        for item in history.get("items", ())
    ]
    active = dashboard_active_session(coordinator)
    history["items"] = (
        [active] + items[: DASHBOARD_SESSION_LIMIT - 1]
        if active is not None
        else items[:DASHBOARD_SESSION_LIMIT]
    )
    return {"schema": 1, **history}


def _encoded_size(value: object) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    )


def _enforce_card_attribute_budget(attributes: dict) -> dict:
    """Keep the state payload below HA's recorder limit with headroom."""
    if _encoded_size(attributes) <= CARD_ATTRIBUTE_TARGET_BYTES:
        return attributes

    sessions = attributes.get("sessions")
    if not isinstance(sessions, dict):
        return attributes
    items = sessions.get("items")
    if not isinstance(items, list):
        return attributes

    # Detail for completed sessions is available through the websocket and is
    # therefore the first safe data to remove from the continuously published
    # state. Keep the active curve because it does not exist in the CSV yet.
    for item in reversed(items):
        if not isinstance(item, dict) or item.get("active"):
            continue
        if any(field in item for field in _SESSION_DETAIL_FIELDS):
            item["detail_available"] = True
            for field in _SESSION_DETAIL_FIELDS:
                item.pop(field, None)
        if _encoded_size(attributes) <= CARD_ATTRIBUTE_TARGET_BYTES:
            return attributes

    while len(items) > 10 and _encoded_size(attributes) > CARD_ATTRIBUTE_TARGET_BYTES:
        items.pop()

    active = next(
        (
            item
            for item in items
            if isinstance(item, dict) and item.get("active")
        ),
        None,
    )
    if active is not None:
        for limit in (64, 48, 32, 24):
            active["power_curve"] = downsample_curve(
                active.get("power_curve"),
                limit=limit,
                event_times=(
                    event.get("at")
                    for event in active.get("events", ())
                    if isinstance(event, dict)
                ),
            )
            if _encoded_size(attributes) <= CARD_ATTRIBUTE_TARGET_BYTES:
                return attributes

    while len(items) > 1 and _encoded_size(attributes) > CARD_ATTRIBUTE_TARGET_BYTES:
        items.pop()

    size = _encoded_size(attributes)
    if size > CARD_ATTRIBUTE_TARGET_BYTES:
        _LOGGER.warning(
            "THOR card data remains above target after safe compaction: %d bytes",
            size,
        )
    return attributes



def _pv_linkage_card_data(coordinator, working_mode, grid_import_limit):
    """Expose the safe configuration snapshot needed by the guided dialog."""
    draft_factory = getattr(coordinator, "pv_linkage_draft", None)
    draft = draft_factory() if callable(draft_factory) else None
    blocked_reason = None
    if not bool(getattr(coordinator, "connected", False)):
        blocked_reason = "charger_disconnected"
    elif bool(getattr(coordinator, "charger_is_faulted", False)):
        blocked_reason = "charger_faulted"
    elif bool(getattr(coordinator, "transaction_is_active", False)):
        blocked_reason = "active_transaction"
    elif not bool(getattr(coordinator, "external_meter_ready_for_pv", False)):
        blocked_reason = "external_meter_not_ready"
    elif any(
        value is not None and value.readonly is True
        for key in ("G_SolarMode", "G_SolarLimitPower", "G_SolarBoost", "G_PeriodTime")
        if (value := coordinator.configuration_values.get(key)) is not None
    ):
        blocked_reason = "configuration_read_only"

    last_apply = getattr(coordinator, "pv_linkage_apply_result", None)
    return {
        "working_mode": (
            working_mode
            if working_mode in {"pv_linkage", "pv_linkage_plus"}
            else "pv_linkage_plus"
        ),
        "grid_import_limit_kw": _number(grid_import_limit),
        "boost_mode": draft.boost_mode.value if draft is not None else "disabled",
        "manual_start": (
            draft.manual_start.strftime("%H:%M")
            if draft is not None and draft.manual_start is not None
            else None
        ),
        "manual_end": (
            draft.manual_end.strftime("%H:%M")
            if draft is not None and draft.manual_end is not None
            else None
        ),
        "smart_finish": (
            draft.smart_finish.strftime("%H:%M")
            if draft is not None and draft.smart_finish is not None
            else None
        ),
        "smart_target_energy_kwh": (
            draft.smart_target_energy_kwh if draft is not None else None
        ),
        "draft_dirty": bool(getattr(coordinator, "pv_linkage_draft_dirty", False)),
        "last_apply": last_apply.as_dict() if last_apply is not None else None,
        "blocked_reason": blocked_reason,
    }


def dashboard_attributes(coordinator) -> dict:
    """Expose only fields required by the bundled card on the status entity."""
    snapshot = coordinator.last_meter_values or {}
    status = (coordinator.last_status_notification or {}).get("request", {})
    start = ((coordinator.active_transaction or {}).get("start") or {})
    model = boot_notification_field(coordinator.boot_notification, "charge_point_model")
    firmware = boot_notification_field(coordinator.boot_notification, "firmware_version")
    grid_import_limit = configuration_entity_state(
        "G_SolarLimitPower",
        coordinator.configuration_values.get("G_SolarLimitPower"),
    )
    working_mode = selected_working_mode(coordinator.configuration_values)
    meter_display = dashboard_meter_values(snapshot)
    charging_sources = None
    sample_at = parse_at(meter_display.get("sample_at"))
    received_at = parse_at(snapshot.get("received_at"))
    now_method = getattr(coordinator, "now", None)
    now = parse_at(now_method()) if callable(now_method) else datetime.now(timezone.utc)
    power_w = meter_display.get("power_w")
    if (sample_at is not None and received_at is not None and now is not None and power_w is not None
            and power_w >= 0 and 0 <= (now - sample_at).total_seconds() <= coordinator._effective_meter_gap_seconds()
            and 0 <= (now - received_at).total_seconds() <= coordinator._effective_meter_gap_seconds()
            and bool(getattr(coordinator, "transaction_is_active", False))):
        # Live sources have independent update schedules; evaluate them now,
        # after checking the charger's sample and receipt are both still fresh.
        inputs = site_inputs(coordinator, now)
        if inputs is not None:
            live = allocate(EVEnergyDelta(
                coordinator.source_instance_id or "site",
                coordinator.charge_point_id or "charger",
                str(coordinator.transaction_id),
                now - timedelta(seconds=1), now, power_w / 3_600_000,
            ), *inputs)
            charging_sources = {
                "solar_w": live.direct_solar * 3_600_000,
                "grid_w": live.direct_grid * 3_600_000,
                "battery_w": live.battery_unknown * 3_600_000,
                "unknown_w": 0.0,
            }
            charging_sources["unknown_w"] = max(0.0, power_w - sum(
                charging_sources[key] for key in ("solar_w", "grid_w", "battery_w")
            ))
    attributes = {
        "schema": 1,
        "charging_target_pilot": getattr(coordinator, "charging_target_pilot_enabled", False),
        "connection_started_at": getattr(coordinator, "connection_started_at", None),
        "charging_target": {
            key: value for key, value in (getattr(coordinator, "charging_target_request", None) or {}).items()
            if key in {
                "request_id",
                "kind",
                "value",
                "state",
                "activation",
                "updated_at",
                "connection_started_at",
                "scheduled_for",
                "recurrence",
                "last_run_at",
                "last_run_state",
                "enforcement_verified",
            }
        } or None,
        "entry_id": coordinator.source_instance_id,
        "working_mode": working_mode,
        "auth_mode": configuration_entity_state("G_ChargerMode", coordinator.configuration_values.get("G_ChargerMode")),
        "transaction_active": coordinator.transaction_is_active,
        "session_started_at": start.get("received_at"),
        "session_energy_kwh": (_number(coordinator.energy) / 1000 if _number(coordinator.energy) is not None else None),
        "meter_received_at": snapshot.get("received_at"),
        "meter_stale_after": coordinator._effective_meter_gap_seconds(),
        **meter_display,
        "max_current_a": maximum_charging_current(model, firmware),
        **charging_power_identity(model, firmware),
        "configured_current_a": _number(getattr(coordinator, "max_current", None)),
        "status_info": status.get("info"),
        "error_code": status.get("error_code"),
        "external_meter_health": coordinator.external_meter_health,
        # Positive is import and negative is export, matching Growatt meter
        # convention. Keep this as a nested, extensible flow snapshot so future
        # PV and battery measurements do not require more top-level card fields.
        "power_flow": {
            "received_at": getattr(coordinator, "external_meter_last_updated_at", None),
            "stale_after_s": max(
                15,
                int(getattr(coordinator, "external_meter_poll_interval", 30)) * 3 + 5,
            ),
            "grid_w": _signed_number(getattr(coordinator, "grid_power", None)),
            "grid_sign": "positive_import",
            "grid_import_limit_kw": _number(grid_import_limit),
            **battery_power_attributes(coordinator),
            **({"charging_sources": charging_sources} if charging_sources is not None else {}),
        },
        "pv_linkage": _pv_linkage_card_data(
            coordinator,
            working_mode,
            grid_import_limit,
        ),
        "command": getattr(coordinator, "dashboard_command", None),
        "energy_stop": getattr(coordinator, "last_energy_stop", None),
        "sessions": dashboard_sessions(coordinator),
    }
    return _enforce_card_attribute_budget(attributes)
