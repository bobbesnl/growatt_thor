"""Coordinator state as persisted in the entry's HA store.

The payload keys and value shapes are a storage contract
(tests/fixtures/session_storage_contract.json); keep them byte-identical.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..charging.faults import ChargerFault
from ..energy.session_accumulator import SessionAccumulator
from ..sessions.active_state import ActiveSessionState
from ..sessions.duration import EffectiveChargingTracker
from ..sessions.state import LastSessionState, normalize_record_key

if TYPE_CHECKING:
    from ..coordinator import GrowattCoordinator


def restore_storage_data(coordinator: GrowattCoordinator, data: dict[str, Any]) -> None:
    """Apply a loaded storage payload to a freshly created coordinator."""
    # Import restoration policy only when executor-loaded storage needs it.
    from ..energy.stop_guard_policy import restore_stop_report

    coordinator.last_energy_stop = restore_stop_report(data.get("last_energy_stop"))
    coordinator.sessions.outbox.restore(data.get("pending_session_rows"))
    coordinator.total_energy_charged = float(data.get("total_energy_charged", 0.0))
    coordinator._transaction_id_allocator.restore(data.get("next_transaction_id", 1))
    coordinator.sessions.last_session = LastSessionState.from_dict(data.get("last_session"))
    stored_keys = data.get("applied_session_record_keys", [])
    if isinstance(stored_keys, list):
        for value in stored_keys[-50:]:
            record_key = normalize_record_key(value)
            if (
                record_key is not None
                and record_key not in coordinator.sessions.applied_session_record_keys
            ):
                coordinator.sessions.applied_session_record_keys.append(record_key)
    if (
        coordinator.sessions.last_session.record_key is not None
        and coordinator.sessions.last_session.record_key
        not in coordinator.sessions.applied_session_record_keys
    ):
        coordinator.sessions.applied_session_record_keys.append(
            coordinator.sessions.last_session.record_key
        )
    coordinator.last_charger_fault = ChargerFault.from_dict(data.get("last_charger_fault"))
    coordinator.effective_charging = EffectiveChargingTracker.from_dict(
        data.get("active_effective_charging")
    )
    active_session = ActiveSessionState.from_dict(data.get("active_session"))
    if active_session.transaction_id is None:
        # Migration from stores written before the active dashboard
        # row was persisted. The effective tracker still provides an
        # honest transaction identity and last observed energy value.
        active_session = ActiveSessionState(
            transaction_id=coordinator.effective_charging.transaction_id,
            energy_wh=coordinator.effective_charging.last_energy_wh,
        )
    coordinator.sessions.restore_active_session_state(active_session)
    coordinator.site_accounting = SessionAccumulator.from_dict(data.get("active_site_accounting"))
    coordinator.last_site_accounting = SessionAccumulator.from_dict(
        data.get("pending_site_accounting")
    )
    stored_totals = data.get("site_accounting_totals")
    if isinstance(stored_totals, dict):
        for key in coordinator.site_accounting_totals:
            try:
                value = float(stored_totals.get(key, 0))
            except (TypeError, ValueError):
                continue
            if value == value and (value >= 0 or key == "effective_grid_cost"):
                coordinator.site_accounting_totals[key] = value
    pending_effective = data.get("pending_effective_charging_minutes")
    if isinstance(pending_effective, dict):
        for key, value in pending_effective.items():
            try:
                coordinator.sessions.pending_effective_charging_minutes[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
    coordinator.sessions.restore_completions(data.get("pending_completed_sessions"))


def storage_data(coordinator: GrowattCoordinator) -> dict[str, object]:
    """Build the current JSON-safe persistent payload."""
    active_session = coordinator.sessions.active_session_state()
    return {
        "pending_session_rows": coordinator.sessions.outbox.snapshot(),
        "pending_completed_sessions": coordinator.sessions.pending_completions,
        "last_energy_stop": coordinator.last_energy_stop,
        "total_energy_charged": coordinator.total_energy_charged,
        "next_transaction_id": coordinator._transaction_id_allocator.next_transaction_id,
        "last_session": coordinator.sessions.last_session.as_dict(),
        "applied_session_record_keys": [
            list(key) for key in coordinator.sessions.applied_session_record_keys
        ],
        "last_charger_fault": (
            coordinator.last_charger_fault.as_dict()
            if coordinator.last_charger_fault is not None
            else None
        ),
        "active_effective_charging": coordinator.effective_charging.as_dict(),
        "active_session": (active_session.as_dict() if active_session is not None else None),
        "active_site_accounting": (
            coordinator.site_accounting.as_dict() if coordinator.site_accounting else None
        ),
        "pending_site_accounting": (
            coordinator.last_site_accounting.as_dict() if coordinator.last_site_accounting else None
        ),
        "site_accounting_totals": dict(coordinator.site_accounting_totals),
        "pending_effective_charging_minutes": dict(
            coordinator.sessions.pending_effective_charging_minutes
        ),
    }
