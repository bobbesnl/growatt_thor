"""Diagnostics support for Growatt THOR."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .configuration import (
    INFORMATIONAL_CONFIGURATION_KEYS,
    OPERATIONAL_CONFIGURATION_KEYS,
    serialize_configuration_values,
)
from .const import DOMAIN
from .ocpp_diagnostics import redact_ocpp_data


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
                "transactions": {
                    "active": None,
                    "last_completed": None,
                },
            },
            "configuration": {},
            "unknown_configuration_keys": [],
        }

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
                "transactions": {
                    "active": coordinator.active_transaction,
                    "last_completed": coordinator.last_completed_transaction,
                },
            }
        ),
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
