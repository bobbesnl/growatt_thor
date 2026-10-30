"""Explicit ownership rules for the integration's per-entry runtime.

Every config entry owns one runtime mapping.  It is stored as
``hass.data[DOMAIN][entry_id]`` and the entry's coordinator keeps a reference
to it as ``coordinator.runtime_data``.  The mapping holds that entry's
coordinator, OCPP server, poll task, poll pause and active OCPP connection.

Nothing that belongs to one charger lives directly under ``hass.data[DOMAIN]``.
A second config entry therefore gets its own runtime instead of replacing the
first one, and an entity can only ever reach the charger whose state it
displays (backlog F09).  Within one runtime the rules below still bind the
entry to a single charge-point identity across reconnects.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from enum import Enum

from .entry import EntryRuntime
from .keys import ACTIVE_CHARGE_POINT as ACTIVE_CHARGE_POINT
from .keys import RUNTIME_CONFIG_ENTRY_ID as RUNTIME_CONFIG_ENTRY_ID


def claim_entry_runtime(
    domain_data: MutableMapping[str, object],
    entry_id: str,
) -> EntryRuntime | None:
    """Create and claim the runtime of one config entry.

    Returns ``None`` when the entry already has a runtime, for example when
    Home Assistant races two setups of the same entry.  Other entries are
    never affected.
    """
    if entry_id in domain_data:
        return None
    runtime_data = EntryRuntime()
    claim_runtime_entry(runtime_data, entry_id)
    domain_data[entry_id] = runtime_data
    return runtime_data


def entry_runtime_data(
    domain_data: Mapping[str, object],
    entry_id: str,
) -> MutableMapping[str, object] | None:
    """Return the loaded runtime of ``entry_id``, if any."""
    runtime_data = domain_data.get(entry_id)
    if isinstance(runtime_data, MutableMapping) and runtime_entry_is_owner(runtime_data, entry_id):
        return runtime_data
    return None


def loaded_entry_runtimes(
    domain_data: Mapping[str, object],
) -> list[tuple[str, MutableMapping[str, object]]]:
    """Return ``(entry_id, runtime)`` for every loaded config entry."""
    return [
        (entry_id, runtime_data)
        for entry_id, runtime_data in domain_data.items()
        if isinstance(runtime_data, MutableMapping)
        and runtime_entry_is_owner(runtime_data, entry_id)
    ]


def release_entry_runtime(
    domain_data: MutableMapping[str, object],
    entry_id: str,
    runtime_data: MutableMapping[str, object],
) -> bool:
    """Remove one entry's runtime, only if it is still the registered one."""
    if domain_data.get(entry_id) is not runtime_data:
        return False
    domain_data.pop(entry_id, None)
    runtime_data.clear()
    return True


class ChargePointConnectionDecision(str, Enum):
    """Describe whether an incoming OCPP connection may own the runtime."""

    ACCEPT_FIRST = "accept_first"
    ACCEPT_RECONNECT = "accept_reconnect"
    REPLACE_SAME_CHARGER = "replace_same_charger"
    REJECT_DIFFERENT_CHARGER = "reject_different_charger"


def claim_runtime_entry(
    runtime_data: MutableMapping[str, object],
    entry_id: str,
) -> bool:
    """Claim one entry's runtime without overwriting an existing owner."""
    if RUNTIME_CONFIG_ENTRY_ID in runtime_data:
        return False
    runtime_data[RUNTIME_CONFIG_ENTRY_ID] = entry_id
    return True


def runtime_entry_is_owner(
    runtime_data: MutableMapping[str, object],
    entry_id: str,
) -> bool:
    """Return whether ``entry_id`` owns this runtime mapping."""
    return runtime_data.get(RUNTIME_CONFIG_ENTRY_ID) == entry_id


def release_active_charge_point(
    runtime_data: MutableMapping[str, object],
    charge_point: object,
) -> bool:
    """Release the socket slot only when ``charge_point`` still owns it."""
    if runtime_data.get(ACTIVE_CHARGE_POINT) is not charge_point:
        return False
    runtime_data.pop(ACTIVE_CHARGE_POINT, None)
    return True


def decide_charge_point_connection(
    *,
    retained_charge_point_id: str | None,
    active_charge_point_id: str | None,
    incoming_charge_point_id: str,
) -> ChargePointConnectionDecision:
    """Decide whether an incoming charger may take the active socket slot.

    ``retained_charge_point_id`` survives a disconnect for the lifetime of the
    loaded config entry.  This prevents a different charger from silently
    inheriting entities and session state before an intentional reload.
    """
    known_ids = {
        charge_point_id
        for charge_point_id in (
            retained_charge_point_id,
            active_charge_point_id,
        )
        if charge_point_id is not None
    }
    if known_ids and known_ids != {incoming_charge_point_id}:
        return ChargePointConnectionDecision.REJECT_DIFFERENT_CHARGER
    if active_charge_point_id is not None:
        return ChargePointConnectionDecision.REPLACE_SAME_CHARGER
    if retained_charge_point_id is not None:
        return ChargePointConnectionDecision.ACCEPT_RECONNECT
    return ChargePointConnectionDecision.ACCEPT_FIRST


def resolve_entry_runtime(domain_data, entry_id=None):
    """Select a charger without ever guessing between multiple loaded entries."""
    if entry_id is not None:
        runtime = entry_runtime_data(domain_data, entry_id)
        if runtime is None:
            raise ValueError("growatt_thor_entry_not_loaded")
        return runtime
    entries = loaded_entry_runtimes(domain_data)
    if len(entries) != 1:
        raise ValueError(
            "growatt_thor_entry_id_required" if entries else "growatt_thor_entry_not_loaded"
        )
    return entries[0][1]
