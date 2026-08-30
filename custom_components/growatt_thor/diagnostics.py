"""Diagnostics support for Growatt THOR."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .charging_sessions import build_unified_session
from .configuration import (
    INFORMATIONAL_CONFIGURATION_KEYS,
    OPERATIONAL_CONFIGURATION_KEYS,
    redact_configuration_value,
    serialize_configuration_values,
)
from .configuration_writes import serialize_configuration_writes
from .const import DOMAIN
from .ocpp_diagnostics import redact_ocpp_data
from .session_records import session_record_diagnostics


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator = hass.data.get(DOMAIN, {}).get("coordinator")
    if coordinator is None:
        return {
            "ocpp": {
                "boot_notification": None,
                "last_status_notification": None,
                "last_meter_values": None,
                "transactions": {
                    "active": None,
                    "last_completed": None,
                },
            },
            "configuration": {},
            "configuration_writes": {},
            "unknown_configuration_keys": [],
            "growatt": {
                "external_meter": {
                    "health": "not_reported",
                    "last_updated_at": None,
                    "consecutive_timeouts": 0,
                    "fault_connector_id": None,
                    "fault_error_code": None,
                    "fault_info": None,
                },
                "session_records": {
                    "current": None,
                    "frozen": None,
                }
            },
            "sessions": {
                "active": None,
                "last_completed": None,
            },
        }

    session_records = (
        coordinator.last_current_record,
        coordinator.last_frozen_record,
    )
    configuration_writes = serialize_configuration_writes(
        coordinator.configuration_writes,
    )
    for key, write in configuration_writes.items():
        write["requested_raw_value"] = redact_configuration_value(
            key,
            write["requested_raw_value"],
        )
        write["reported_raw_value"] = redact_configuration_value(
            key,
            write["reported_raw_value"],
        )

    active_transaction = (
        dict(coordinator.active_transaction)
        if coordinator.active_transaction is not None
        else None
    )
    if active_transaction is not None:
        active_transaction["effective_charging_duration_minutes"] = (
            coordinator.effective_charging.effective_minutes
        )

    return {
        "connection": {
            "connected": coordinator.connected,
            "status": coordinator.status,
            "connection_started_at": coordinator.connection_started_at,
            "last_message_at": coordinator.last_message_at,
            "last_message_action": coordinator.last_message_action,
            "last_heartbeat_at": coordinator.last_heartbeat_at,
        },
        "ocpp": redact_ocpp_data(
            {
                "boot_notification": coordinator.boot_notification,
                "last_status_notification": coordinator.last_status_notification,
                "last_meter_values": coordinator.last_meter_values,
                "transactions": {
                    "active": active_transaction,
                    "last_completed": coordinator.last_completed_transaction,
                },
            }
        ),
        "growatt": {
            "external_meter": {
                "health": coordinator.external_meter_health,
                "last_updated_at": coordinator.external_meter_last_updated_at,
                "consecutive_timeouts": coordinator.meterval_consecutive_timeouts,
                "fault_connector_id": coordinator.external_meter_fault_connector_id,
                "fault_error_code": coordinator.external_meter_fault_error_code,
                "fault_info": coordinator.external_meter_fault_info,
            },
            "session_records": {
                "current": session_record_diagnostics(
                    coordinator.last_current_record
                ),
                "frozen": session_record_diagnostics(
                    coordinator.last_frozen_record
                ),
            }
        },
        "sessions": {
            "active": (
                build_unified_session(
                    active_transaction,
                    meter_values=coordinator.last_meter_values,
                    session_records=session_records,
                    charge_point_id=coordinator.charge_point_id,
                    source_instance_id=coordinator.source_instance_id,
                )
                if coordinator.active_transaction is not None
                else None
            ),
            "last_completed": build_unified_session(
                coordinator.last_completed_transaction,
                meter_values=coordinator.last_meter_values,
                session_records=session_records,
                charge_point_id=coordinator.charge_point_id,
                source_instance_id=coordinator.source_instance_id,
            ),
        },
        "configuration": serialize_configuration_values(
            coordinator.configuration_values,
            redact=True,
        ),
        "configuration_writes": configuration_writes,
        "unknown_configuration_keys": list(
            coordinator.unknown_configuration_keys
        ),
        "requested_configuration_keys": {
            "operational": list(OPERATIONAL_CONFIGURATION_KEYS),
            "informational": list(INFORMATIONAL_CONFIGURATION_KEYS),
        },
    }
