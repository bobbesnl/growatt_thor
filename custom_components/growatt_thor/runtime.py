"""Per config entry runtime state for Growatt THOR.

Every config entry runs its own OCPP server and coordinator. Their runtime
objects live under hass.data[DOMAIN][entry_id] so that several chargers can
run side by side without overwriting each other's state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .const import DOMAIN, DEFAULT_POLL_INTERVAL


@dataclass
class GrowattRuntimeData:
    """Runtime objects owned by one config entry."""

    coordinator: Any
    server: Any = None
    polling_task: Any = None
    poll_interval: int = DEFAULT_POLL_INTERVAL


def get_runtime_data(hass, entry_id: str) -> GrowattRuntimeData | None:
    """Return the runtime data of one config entry, if it is loaded."""
    value = hass.data.get(DOMAIN, {}).get(entry_id)
    return value if isinstance(value, GrowattRuntimeData) else None


def get_coordinator(hass, entry_id: str):
    """Return the coordinator of one config entry, if it is loaded."""
    runtime = get_runtime_data(hass, entry_id)
    return runtime.coordinator if runtime else None


def find_device_with_identifier(devices, identifier):
    """Return the first device whose identifiers contain identifier.

    Pass the devices of one config entry, from
    device_registry.async_entries_for_config_entry. That keeps the lookup
    within the entry without device_registry.async_get_device (deprecated
    since Home Assistant 2026.9) or async_get_device_by_identifier (only
    available since 2026.8), so it works on every Home Assistant version.
    """
    for device in devices:
        if identifier in device.identifiers:
            return device
    return None


def iter_runtime_data(hass) -> list[tuple[str, GrowattRuntimeData]]:
    """Return (entry_id, runtime data) for every loaded config entry."""
    return [
        (entry_id, value)
        for entry_id, value in hass.data.get(DOMAIN, {}).items()
        if isinstance(value, GrowattRuntimeData)
    ]
