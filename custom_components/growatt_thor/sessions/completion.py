"""Bounded OCPP completion retained until the vendor record arrives."""

from collections.abc import Mapping
from math import isfinite

from .active_state import ActiveSessionState
from .telemetry import context_curves


def completion_transaction(value: object) -> dict | None:
    if not isinstance(value, Mapping):
        return None
    start = value.get("start")
    stop = value.get("stop")
    if not isinstance(start, Mapping) or not isinstance(stop, Mapping):
        return None
    request = start.get("request", {})
    response = start.get("response", {})
    stopped = stop.get("request", {})
    if not all(isinstance(item, Mapping) for item in (request, response, stopped)):
        return None
    tx = response.get("transaction_id")
    if tx is None or str(tx) != str(stopped.get("transaction_id")):
        return None
    bounded = ActiveSessionState.from_dict(
        {
            "transaction_id": tx,
            "id_tag": request.get("id_tag"),
            "id_tag_alias": value.get("id_tag_alias"),
            "connector_id": request.get("connector_id"),
            "meter_start": request.get("meter_start"),
            "start_received_at": start.get("received_at"),
            "start_timestamp": request.get("timestamp"),
            **context_curves(value),
            "site_house_load_source": value.get("site_house_load_source"),
            "events": value.get("events"),
            "power_curve": value.get("power_curve"),
        }
    )
    stop_request = {}
    for key in ("transaction_id", "meter_stop", "reason", "timestamp", "id_tag"):
        item = stopped.get(key)
        if isinstance(item, str):
            stop_request[key] = item[:256]
        elif isinstance(item, (int, float)) and isfinite(item):
            stop_request[key] = item
    minutes = value.get("effective_charging_duration_minutes")
    if not isinstance(minutes, (int, float)) or not isfinite(minutes) or minutes < 0:
        minutes = None
    return {
        "id_tag_alias": bounded.id_tag_alias,
        "start": {
            "received_at": bounded.start_received_at,
            "request": {
                "id_tag": bounded.id_tag,
                "connector_id": bounded.connector_id,
                "meter_start": bounded.meter_start,
                "timestamp": bounded.start_timestamp,
            },
            "response": {"transaction_id": bounded.transaction_id},
        },
        "stop": {
            "received_at": str(stop.get("received_at", ""))[:256],
            "request": stop_request,
        },
        **bounded.context_curves,
        **(
            {"site_house_load_source": bounded.site_house_load_source}
            if bounded.site_house_load_source
            else {}
        ),
        "events": bounded.events,
        "power_curve": bounded.power_curve,
        "effective_charging_duration_minutes": minutes,
    }
