"""Explicit ownership rules for the integration's domain-global runtime.

The 1.7 architecture stores one coordinator and one active OCPP connection in
``hass.data[DOMAIN]``.  Until multi-charger routing exists, accepting multiple
owners would be worse than rejecting them: an entity could otherwise write to
a different charger than the one whose state it displays.
"""
from __future__ import annotations

from enum import Enum
from typing import Final, MutableMapping


RUNTIME_CONFIG_ENTRY_ID: Final = "config_entry_id"
ACTIVE_CHARGE_POINT: Final = "charge_point"


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
    """Claim the single-entry runtime without overwriting an existing owner."""
    if RUNTIME_CONFIG_ENTRY_ID in runtime_data:
        return False
    runtime_data[RUNTIME_CONFIG_ENTRY_ID] = entry_id
    return True


def runtime_entry_is_owner(
    runtime_data: MutableMapping[str, object],
    entry_id: str,
) -> bool:
    """Return whether ``entry_id`` owns the domain-global runtime."""
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
