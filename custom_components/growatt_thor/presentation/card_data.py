"""Small, display-safe dashboard view of retained charger observations.

Use the latest MeterValues packet, not the accumulated sensor dictionaries:
otherwise an omitted phase can incorrectly look active from an earlier packet.
Only the identifier and card name retained for a session are exposed;
authorisation policy, configured allowlists, raw packets and credentials remain private.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from typing import Any, cast

from ..charging.control_capabilities import selected_working_mode
from ..charging.limits import charging_power_identity, maximum_charging_current
from ..charging.snapshot import ChargerSnapshot, ChargerStateOwner, charger_snapshot
from ..coerce import optional_float, optional_text
from ..configuration.values import ConfigurationScalar, configuration_entity_state
from ..energy.live_allocation import live_charging_sources
from ..energy.meter_observations import ChargingMeterObservation
from ..energy.meter_observations import (
    charging_meter_values as dashboard_meter_values,  # noqa: F401  (card tests parse raw packets)
)
from ..ocpp.diagnostics import boot_notification_field
from ..ocpp.meter_samples import meter_time_zone, normalize_meter_timestamp
from ..sessions.display_times import session_times
from ..sessions.events import normalize_session_events
from ..sessions.identity import SOURCE_HOME_ASSISTANT, build_session_id
from ..sessions.series import SESSION_CURVE_POINT_LIMIT, downsample_curve
from ..sessions.telemetry import CONTEXT_CURVES, context_curves
from ..timestamps import installation_time_zone, utc_timestamp
from .battery import battery_power_attributes
from .contracts import ActiveSessionOwner, DashboardOwner

_LOGGER = logging.getLogger(__name__)
DASHBOARD_SESSION_LIMIT = 20
# HA state updates carry this projection repeatedly. Full history belongs in
# CSV/WebSocket detail; increasing this budget also increases recorder traffic.
CARD_ATTRIBUTE_TARGET_BYTES = 12 * 1024
_SESSION_DETAIL_FIELDS = ("power_curve", "events", *CONTEXT_CURVES)


def live_dashboard_meter_values(coordinator: ChargerStateOwner) -> ChargingMeterObservation:
    """Keep the card consistent with live sensors without changing raw samples."""
    return charger_snapshot(coordinator).live_meter().as_observation()


def _number(value: object) -> float | None:
    return optional_float(value, minimum=0)


def _signed_number(value: object) -> float | None:
    """Return a finite signed number, preserving grid import/export direction."""
    return optional_float(value)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str | None:
    return optional_text(value)


def _dashboard_power_curve(value: object, *, event_times: Iterable[object] = ()) -> list[list[Any]]:
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


def dashboard_active_session(coordinator: ActiveSessionOwner) -> dict[str, Any] | None:
    """Build the transient row for the transaction currently in progress."""
    if not bool(coordinator.transaction_is_active):
        return None

    transaction = _mapping(coordinator.active_transaction)
    start = _mapping(transaction.get("start"))
    request = _mapping(start.get("request"))
    response = _mapping(start.get("response"))
    transaction_id = _text(coordinator.transaction_id or response.get("transaction_id"))
    start_time = _text(request.get("timestamp") or start.get("received_at"))
    energy_wh = _number(coordinator.energy)
    events = normalize_session_events(transaction.get("events"))
    accounting = coordinator.site_accounting
    metered_kwh = sum(accounting.buckets.values()) if accounting is not None else None
    fallback_kwh = accounting.power_fallback_kwh if accounting is not None else 0.0
    sessions = coordinator.sessions
    telemetry = sessions.telemetry
    return {
        "session_id": build_session_id(
            source=SOURCE_HOME_ASSISTANT,
            source_instance_id=coordinator.source_instance_id,
            charge_point_id=coordinator.charge_point_id,
            transaction_id=transaction_id,
            started_at=start_time,
        ),
        "active": True,
        # Keep the raw start in the identity above; normalize only the display.
        "start_time": normalize_meter_timestamp(
            start_time,
            meter_time_zone(
                coordinator.configuration_values,
                installation_time_zone(coordinator.hass),
            ),
        ),
        "end_time": None,
        "energy_kwh": (
            metered_kwh
            if metered_kwh is not None and metered_kwh > 0
            else fallback_kwh
            if fallback_kwh > 0
            else 0.0
            if accounting is not None
            else energy_wh / 1000
            if energy_wh is not None
            else None
        ),
        "energy_source": (
            "ocpp_meter"
            if metered_kwh is not None and metered_kwh > 0
            else "power_fallback"
            if fallback_kwh > 0
            else None
        ),
        "green_energy_kwh": None,
        **(
            accounting.as_session_dict()
            if accounting is not None and metered_kwh is not None and metered_kwh > 0
            else {}
        ),
        # Growatt reports the authoritative cost only with the completed record.
        "cost": None,
        "duration_minutes": None,
        "authorized_identifier": _text(request.get("id_tag") or coordinator.id_tag),
        "authorized_alias": _text(transaction.get("id_tag_alias")),
        "power_curve": _dashboard_power_curve(
            sessions.active_power_curve,
            event_times=(event.get("at") for event in events),
        ),
        **(telemetry.metadata() if telemetry is not None else {}),
        **(
            telemetry.snapshot(event_times=(event.get("at") for event in events))
            if telemetry is not None
            else {}
        ),
        "events": events,
        "detail_available": True,
    }


def dashboard_sessions(coordinator: ActiveSessionOwner) -> dict[str, Any]:
    """Combine bounded completed history with one optional active row."""
    history = dict(coordinator.dashboard_sessions or {})
    items = [dict(item) if isinstance(item, Mapping) else item for item in history.get("items", ())]
    active = dashboard_active_session(coordinator)
    history["items"] = (
        [active] + items[: DASHBOARD_SESSION_LIMIT - 1]
        if active is not None
        else items[:DASHBOARD_SESSION_LIMIT]
    )
    zone = installation_time_zone(coordinator.hass)
    history["items"] = [
        session_times(item, zone) if isinstance(item, Mapping) else item
        for item in history["items"]
    ]
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


def _enforce_card_attribute_budget(attributes: dict[str, Any]) -> dict[str, Any]:
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
        (item for item in items if isinstance(item, dict) and item.get("active")),
        None,
    )
    if active is not None:
        for limit in (64, 48, 32, 24):
            active["power_curve"] = downsample_curve(
                active.get("power_curve"),
                limit=limit,
                event_times=(
                    event.get("at") for event in active.get("events", ()) if isinstance(event, dict)
                ),
            )
            active.update(
                context_curves(
                    active,
                    limit=limit,
                    event_times=(event.get("at") for event in active.get("events", ())),
                )
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


def _pv_linkage_card_data(
    coordinator: DashboardOwner,
    charger: ChargerSnapshot,
    working_mode: str | None,
    grid_import_limit: ConfigurationScalar,
) -> dict[str, Any]:
    """Expose the safe configuration snapshot needed by the guided dialog."""
    draft = coordinator.pv_draft.snapshot()
    blocked_reason = None
    if not charger.connected:
        blocked_reason = "charger_disconnected"
    elif charger.faulted:
        blocked_reason = "charger_faulted"
    elif charger.transaction_active:
        blocked_reason = "active_transaction"
    elif not bool(coordinator.external_meter.ready_for_pv):
        blocked_reason = "external_meter_not_ready"
    elif any(
        value is not None and value.readonly is True
        for key in ("G_SolarMode", "G_SolarLimitPower", "G_SolarBoost", "G_PeriodTime")
        if (value := coordinator.configuration_values.get(key)) is not None
    ):
        blocked_reason = "configuration_read_only"

    last_apply = coordinator.pv_draft.apply_result
    return {
        "working_mode": (
            working_mode if working_mode in {"pv_linkage", "pv_linkage_plus"} else "pv_linkage_plus"
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
        "smart_target_energy_kwh": (draft.smart_target_energy_kwh if draft is not None else None),
        "draft_dirty": bool(coordinator.pv_draft.dirty),
        "last_apply": last_apply.as_dict() if last_apply is not None else None,
        "blocked_reason": blocked_reason,
    }


def dashboard_attributes(coordinator: DashboardOwner) -> dict[str, Any]:
    """Expose only fields required by the bundled card on the status entity."""
    charger = charger_snapshot(coordinator)
    snapshot = coordinator.last_meter_values or {}
    status = (coordinator.last_status_notification or {}).get("request", {})
    transaction: Mapping[str, Any] = coordinator.active_transaction or {}
    start = transaction.get("start") or {}
    model = boot_notification_field(coordinator.boot_notification, "charge_point_model")
    firmware = boot_notification_field(coordinator.boot_notification, "firmware_version")
    grid_import_limit = configuration_entity_state(
        "G_SolarLimitPower",
        coordinator.configuration_values.get("G_SolarLimitPower"),
    )
    working_mode = selected_working_mode(coordinator.configuration_values)
    meter_display = charger.live_meter().as_observation()
    charging_sources = live_charging_sources(coordinator, meter_display, snapshot)
    attributes = {
        "schema": 1,
        "charging_target_pilot": coordinator.charging_target_pilot_enabled,
        "connection_started_at": coordinator.connection_started_at,
        "charging_target": {
            key: value
            for key, value in (coordinator.charging_target_request or {}).items()
            if key
            in {
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
        }
        or None,
        "entry_id": coordinator.source_instance_id,
        "working_mode": working_mode,
        "auth_mode": configuration_entity_state(
            "G_ChargerMode", coordinator.configuration_values.get("G_ChargerMode")
        ),
        "transaction_active": charger.transaction_active,
        "session_started_at": utc_timestamp(
            start.get("received_at"),
            installation_time_zone(coordinator.hass),
        ),
        "session_energy_kwh": (
            cast(float, _number(coordinator.energy)) / 1000
            if _number(coordinator.energy) is not None
            else None
        ),
        "meter_received_at": charger.meter.received_at,
        "meter_stale_after": charger.meter_stale_after_s,
        **meter_display,
        "max_current_a": maximum_charging_current(model, firmware),
        **charging_power_identity(model, firmware),
        "configured_current_a": _number(coordinator.max_current),
        "status_info": status.get("info"),
        "error_code": status.get("error_code"),
        "external_meter_health": coordinator.external_meter.health,
        # Positive is import and negative is export, matching Growatt meter
        # convention. Keep this as a nested, extensible flow snapshot so future
        # PV and battery measurements do not require more top-level card fields.
        "power_flow": {
            "received_at": coordinator.external_meter.last_updated_at,
            "stale_after_s": max(
                15,
                int(coordinator.external_meter.poll_interval) * 3 + 5,
            ),
            "grid_w": _signed_number(coordinator.external_meter.power),
            "grid_sign": "positive_import",
            "grid_import_limit_kw": _number(grid_import_limit),
            **battery_power_attributes(coordinator),
            **({"charging_sources": charging_sources} if charging_sources is not None else {}),
        },
        "pv_linkage": _pv_linkage_card_data(
            coordinator,
            charger,
            working_mode,
            grid_import_limit,
        ),
        "command": coordinator.dashboard_command,
        "energy_stop": coordinator.last_energy_stop,
        "sessions": dashboard_sessions(coordinator),
    }
    return _enforce_card_attribute_budget(attributes)
