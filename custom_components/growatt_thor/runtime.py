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


def iter_runtime_data(hass) -> list[tuple[str, GrowattRuntimeData]]:
    """Return (entry_id, runtime data) for every loaded config entry."""
    return [
        (entry_id, value)
        for entry_id, value in hass.data.get(DOMAIN, {}).items()
        if isinstance(value, GrowattRuntimeData)
    ]
