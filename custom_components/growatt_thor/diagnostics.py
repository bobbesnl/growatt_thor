"""Diagnostics support for Growatt THOR."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .charging_sessions import build_unified_session
from .configuration import (
    INFORMATIONAL_CONFIGURATION_KEYS,
    OPERATIONAL_CONFIGURATION_KEYS,
    serialize_configuration_values,
)
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
            "unknown_configuration_keys": [],
            "growatt": {
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
                    "active": coordinator.active_transaction,
                    "last_completed": coordinator.last_completed_transaction,
                },
            }
        ),
        "growatt": {
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
                    coordinator.active_transaction,
                    meter_values=coordinator.last_meter_values,
                    session_records=session_records,
                )
                if coordinator.active_transaction is not None
                else None
            ),
            "last_completed": build_unified_session(
                coordinator.last_completed_transaction,
                meter_values=coordinator.last_meter_values,
                session_records=session_records,
            ),
        },
        "configuration": serialize_configuration_values(
            coordinator.configuration_values,
            redact=True,
        ),
        "unknown_configuration_keys": list(
            coordinator.unknown_configuration_keys
        ),
        "requested_configuration_keys": {
            "operational": list(OPERATIONAL_CONFIGURATION_KEYS),
            "informational": list(INFORMATIONAL_CONFIGURATION_KEYS),
        },
    }
