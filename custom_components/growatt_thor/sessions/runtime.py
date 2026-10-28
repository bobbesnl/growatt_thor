"""Session lifecycle transitions, independent of dashboard presentation.

The coordinator retains the public observations used by existing entities and
storage. This boundary owns start, stop, recovery and final record processing.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping

from ..energy.session_accounting import SessionAccumulator
from ..ocpp.diagnostics import create_ocpp_snapshot
from ..ocpp.status import LIVE_POWER_STATUSES, normalize_ocpp_status
from ..runtime.time import parse_utc as parse_at
from ..runtime.time import utc_instant, utc_timestamp
from .active_state import ActiveSessionState
from .completion import completion_transaction
from .correlation import CORRELATION_MATCHED, build_unified_session
from .duration import EffectiveChargingTracker
from .events import SessionEventTracker, merge_growatt_record_events
from .outbox import SessionOutbox
from .records import GrowattSessionRecord
from .telemetry import SessionTelemetry, context_curves
from .time import session_time_zone

_LOGGER = logging.getLogger(__name__)


class SessionLifecycle:
    """Apply session transitions to the shared charger observations."""

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.outbox = SessionOutbox()
        self.pending_completions = []
        self.telemetry = SessionTelemetry()

    def observe_context(self, *, notify=True):
        coordinator = self.coordinator
        if coordinator.transaction_id is None or getattr(
            coordinator, "_restored_active_session", False
        ):
            return False
        changed = self.telemetry.observe_context(coordinator, coordinator.now())
        at = parse_at(coordinator.now())
        snapshot = getattr(coordinator, "last_meter_values", None) or {}
        entries = snapshot.get("meter_values", [])
        sampled = parse_at(entries[-1].get("timestamp")) if entries else None
        if (
            not coordinator.connected
            or normalize_ocpp_status(coordinator.status) not in LIVE_POWER_STATUSES
            or sampled is None
            or at is None
            or (at - sampled).total_seconds() > coordinator._effective_meter_gap_seconds()
        ):
            changed = (
                self.telemetry.observe("measured_current_sum_curve_a", coordinator.now(), None)
                or changed
            )
        if changed and notify:
            coordinator._schedule_storage_save()
            coordinator.async_set_updated_data(True)
        return changed

    def observe_meter(self, entry, received_at):
        coordinator = self.coordinator
        if coordinator.transaction_id is None:
            return False
        request = (coordinator.active_transaction or {}).get("start", {}).get("request", {})
        lower = utc_instant(request.get("timestamp"), session_time_zone(coordinator))
        sampled = parse_at(entry.timestamp)
        if lower is not None and sampled is not None and sampled < lower:
            return False
        return self.telemetry.observe_meter(
            entry, received_at, coordinator._effective_meter_gap_seconds()
        )

    def restore_completions(self, value):
        self.pending_completions = []
        for entry in value[-10:] if isinstance(value, list) else ():
            if not isinstance(entry, Mapping):
                continue
            transaction = completion_transaction(entry.get("transaction"))
            if transaction is None:
                continue
            accounting = SessionAccumulator.from_dict(entry.get("accounting"))
            self.pending_completions.append(
                {
                    "transaction": transaction,
                    "accounting": accounting.as_dict() if accounting else None,
                }
            )
        if self.pending_completions:
            latest = self.pending_completions[-1]
            self.coordinator.last_completed_transaction = latest["transaction"]
            self.coordinator.last_site_accounting = SessionAccumulator.from_dict(
                latest["accounting"]
            )

    async def async_flush_pending(self):
        coordinator = self.coordinator
        append_fn = coordinator.runtime_data.get("append_session_to_csv")
        if append_fn is None:
            return
        try:
            await self.outbox.flush(coordinator.async_save_storage, append_fn)
        except Exception:
            _LOGGER.exception("Session delivery deferred; checkpoint retained for retry")

    def _active_session_state(self) -> ActiveSessionState | None:
        """Build the bounded persistent representation of the live session."""
        coordinator = self.coordinator
        transaction = (
            coordinator.active_transaction
            if isinstance(coordinator.active_transaction, Mapping)
            else {}
        )
        start = transaction.get("start") if isinstance(transaction.get("start"), Mapping) else {}
        request = start.get("request") if isinstance(start.get("request"), Mapping) else {}
        response = start.get("response") if isinstance(start.get("response"), Mapping) else {}
        transaction_id = coordinator.transaction_id or response.get("transaction_id")
        if transaction_id is None:
            return None
        events = (
            coordinator._session_event_tracker.events
            if coordinator._session_event_tracker is not None
            else transaction.get("events")
        )
        return ActiveSessionState.from_dict(
            {
                "transaction_id": transaction_id,
                "id_tag": request.get("id_tag") or coordinator.id_tag,
                "id_tag_alias": transaction.get("id_tag_alias"),
                "start_received_at": start.get("received_at"),
                "start_timestamp": request.get("timestamp"),
                "connector_id": request.get("connector_id"),
                "meter_start": request.get("meter_start"),
                "energy_wh": coordinator.energy,
                "power_curve": coordinator._active_power_curve,
                **self.telemetry.snapshot(),
                **self.telemetry.metadata(),
                "events": events,
                "energy_flowing": (
                    coordinator._session_event_tracker.energy_flowing
                    if coordinator._session_event_tracker is not None
                    else None
                ),
            }
        )

    def _restore_active_session_state(self, state: ActiveSessionState) -> None:
        """Restore a live row without inventing timestamps or measurements."""
        coordinator = self.coordinator
        if state.transaction_id is None:
            return
        request = {
            key: value
            for key, value in (
                ("connector_id", state.connector_id),
                ("id_tag", state.id_tag),
                ("meter_start", state.meter_start),
                ("timestamp", state.start_timestamp),
            )
            if value is not None
        }
        # JSON session identities are stored as text; OCPP and the stop guard
        # compare integer transaction IDs received from the charger.
        coordinator.transaction_id = (
            int(state.transaction_id)
            if state.transaction_id.isascii() and state.transaction_id.isdecimal()
            else state.transaction_id
        )
        coordinator.id_tag = state.id_tag
        coordinator.energy = state.energy_wh
        coordinator._active_power_curve = list(state.power_curve)
        self.telemetry = SessionTelemetry(
            {
                **state.context_curves,
                "site_house_load_source": state.site_house_load_source,
            }
        )
        for key in tuple(self.telemetry.curves):
            self.telemetry.observe(key, coordinator.now(), None)
        coordinator._session_event_tracker = SessionEventTracker(
            events=list(state.events),
            energy_flowing=state.energy_flowing,
        )
        coordinator.active_transaction = {
            "id_tag_alias": state.id_tag_alias,
            "start": {
                "received_at": state.start_received_at,
                "request": request,
                "response": {"transaction_id": coordinator.transaction_id},
            },
            "events": coordinator._session_event_tracker.events,
        }
        coordinator._restored_active_session = True

    def _discard_unconfirmed_restored_session(self) -> None:
        """Drop a restored row once the charger explicitly reports available."""
        coordinator = self.coordinator
        if not coordinator._restored_active_session:
            return
        _LOGGER.info(
            "Discarding restored active session %s after Available status",
            coordinator.transaction_id,
        )
        completed = dict(coordinator.active_transaction or {})
        completed["power_curve"] = list(coordinator._active_power_curve)
        completed.update(self.telemetry.snapshot())
        completed.update(self.telemetry.metadata())
        effective_minutes = coordinator.effective_charging.effective_minutes
        completed["effective_charging_duration_minutes"] = effective_minutes
        coordinator.last_completed_transaction = completed
        if coordinator.transaction_id is not None and effective_minutes is not None:
            coordinator._pending_effective_charging_minutes[str(coordinator.transaction_id)] = (
                effective_minutes
            )
            while len(coordinator._pending_effective_charging_minutes) > 10:
                oldest = next(iter(coordinator._pending_effective_charging_minutes))
                coordinator._pending_effective_charging_minutes.pop(oldest)
        coordinator.transaction_id = None
        coordinator.id_tag = None
        coordinator.energy = None
        coordinator.active_transaction = None
        coordinator.site_accounting = None
        coordinator._active_power_curve = []
        self.telemetry = SessionTelemetry()
        coordinator._session_event_tracker = None
        coordinator.effective_charging = EffectiveChargingTracker()
        coordinator._restored_active_session = False
        coordinator._schedule_storage_save()

    def start_transaction(
        self,
        transaction_id,
        id_tag=None,
        *,
        connector_id=None,
        meter_start=None,
        **payload,
    ):
        """Start charging transaction."""
        coordinator = self.coordinator
        coordinator.transaction_id = transaction_id
        coordinator.id_tag = id_tag
        coordinator.status = "Charging"
        # Clear the dashboard notice only on a confirmed new transaction, not
        # on a Start click or reconnect. The old session keeps its stop event.
        coordinator.last_energy_stop = None

        request = {
            "connector_id": connector_id,
            "id_tag": id_tag,
            "meter_start": meter_start,
            **payload,
        }
        start_snapshot = create_ocpp_snapshot(coordinator.now(), request)
        start_snapshot["response"] = {"transaction_id": transaction_id}
        coordinator._session_event_tracker = SessionEventTracker.start(
            start_snapshot["received_at"],
            plugged_event=coordinator._pending_plugged_event,
        )
        coordinator._pending_plugged_event = None
        coordinator.active_transaction = {
            "id_tag_alias": coordinator.authorization.policy.aliases.get(id_tag),
            "start": start_snapshot,
            "events": coordinator._session_event_tracker.events,
        }
        try:
            baseline = float(meter_start) if meter_start is not None else None
        except (TypeError, ValueError):
            baseline = None
        coordinator.site_accounting = (
            SessionAccumulator(
                str(transaction_id),
                meter_start_wh=baseline,
                last_meter_wh=baseline,
                last_meter_at=parse_at(start_snapshot["received_at"]),
            )
            if coordinator.site_accounting_options.get("site_accounting_profile", "disabled")
            != "disabled"
            else None
        )
        coordinator._active_power_curve = []
        self.telemetry = SessionTelemetry()
        coordinator._restored_active_session = False
        coordinator.effective_charging.start(transaction_id)
        self.observe_context(notify=False)
        coordinator._schedule_storage_save()

        _LOGGER.info("New transaction started → Resetting energy counter")
        coordinator.energy = 0

        _LOGGER.info("Transaction started: %s", transaction_id)
        coordinator.async_set_updated_data(True)
        callback = getattr(coordinator, "_charging_target_transaction_started", None)
        if callback is not None:
            coordinator.hass.async_create_task(callback(transaction_id=transaction_id))

    def stop_transaction(
        self,
        reason=None,
        *,
        transaction_id=None,
        meter_stop=None,
        **payload,
    ):
        """Stop charging transaction."""
        coordinator = self.coordinator
        stopped_transaction_id = (
            coordinator.transaction_id if transaction_id is None else transaction_id
        )
        # A delayed or repeated stop must never close a newer session or
        # replace its retained completion details. The protocol still ACKs it.
        active_id = coordinator.transaction_id
        if active_id is None or str(stopped_transaction_id) != str(active_id):
            _LOGGER.info(
                "Ignoring StopTransaction for inactive transaction %s",
                stopped_transaction_id,
            )
            return
        _LOGGER.info(
            "Transaction stopped: %s (reason=%s)",
            stopped_transaction_id,
            reason,
        )

        request = {
            "transaction_id": stopped_transaction_id,
            "meter_stop": meter_stop,
            "reason": reason,
            **payload,
        }
        self.observe_context(notify=False)
        completed = dict(coordinator.active_transaction or {})
        completed["stop"] = create_ocpp_snapshot(coordinator.now(), request)
        if coordinator._session_event_tracker is not None:
            coordinator._session_event_tracker.stop(completed["stop"]["received_at"], reason=reason)
            completed["events"] = list(coordinator._session_event_tracker.events)
        effective_minutes = None
        normalized_transaction_id = (
            str(stopped_transaction_id) if stopped_transaction_id is not None else None
        )
        if coordinator.effective_charging.transaction_id == normalized_transaction_id:
            effective_minutes = coordinator.effective_charging.effective_minutes
        completed["effective_charging_duration_minutes"] = effective_minutes
        completed["power_curve"] = list(coordinator._active_power_curve)
        completed.update(self.telemetry.snapshot())
        completed.update(self.telemetry.metadata())
        if coordinator.site_accounting is not None:
            start_wh = coordinator.site_accounting.meter_start_wh
            try:
                stop_wh = float(meter_stop) if meter_stop is not None else None
            except (TypeError, ValueError):
                stop_wh = None
            if start_wh is not None and stop_wh is not None and stop_wh >= start_wh:
                coordinator.site_accounting.reconcile((stop_wh - start_wh) / 1000)
            coordinator.last_site_accounting = coordinator.site_accounting
            coordinator.site_accounting = None
        coordinator._active_power_curve = []
        self.telemetry = SessionTelemetry()
        coordinator._session_event_tracker = None
        if normalized_transaction_id is not None and effective_minutes is not None:
            coordinator._pending_effective_charging_minutes[normalized_transaction_id] = (
                effective_minutes
            )
            while len(coordinator._pending_effective_charging_minutes) > 10:
                oldest = next(iter(coordinator._pending_effective_charging_minutes))
                coordinator._pending_effective_charging_minutes.pop(oldest)
        coordinator.effective_charging = EffectiveChargingTracker()
        coordinator.last_completed_transaction = completed
        retained = completion_transaction(completed)
        if retained is not None:
            self.pending_completions.append(
                {
                    "transaction": retained,
                    "accounting": coordinator.last_site_accounting.as_dict()
                    if coordinator.last_site_accounting
                    else None,
                }
            )
            self.pending_completions = self.pending_completions[-10:]
        coordinator.active_transaction = None
        coordinator._restored_active_session = False

        _LOGGER.info("Transaction stopped → Resetting charge values")
        coordinator.power = 0
        coordinator.currents = {"L1": 0, "L2": 0, "L3": 0}
        coordinator.voltages = {"L1": 0, "L2": 0, "L3": 0}
        coordinator.phase_power = {"L1": 0, "L2": 0, "L3": 0}

        coordinator.transaction_id = None
        coordinator.status = "Idle"
        coordinator.hass.async_create_task(coordinator.async_save_storage())
        coordinator.async_set_updated_data(True)
        callback = getattr(coordinator, "_charging_target_transaction_stopped", None)
        if callback is not None:
            coordinator.hass.async_create_task(
                callback(transaction_id=stopped_transaction_id, reason=reason)
            )

    def record_stop_requested(self, *, reason="remote_stop") -> None:
        """Record a stop intent at the point it is handed to OCPP."""
        coordinator = self.coordinator
        if coordinator._session_event_tracker is None:
            return
        if coordinator._session_event_tracker.record_stop_requested(
            coordinator.now(), reason=reason
        ):
            coordinator._schedule_storage_save()
            coordinator.async_set_updated_data(True)

    def process_session_record(self, record: GrowattSessionRecord):
        """Retain a Growatt session record and update session statistics."""
        coordinator = self.coordinator
        snapshot = {"received_at": coordinator.now(), "record": record}
        if record.message_id == "currentrecord":
            coordinator.last_current_record = snapshot
        else:
            coordinator.last_frozen_record = snapshot

        completed_transaction = coordinator.last_completed_transaction
        pending_completion = None
        for candidate in reversed(self.pending_completions):
            session = build_unified_session(
                candidate["transaction"],
                session_records=(snapshot,),
                time_zone=session_time_zone(coordinator),
            )
            if session and session["correlation"]["status"] == CORRELATION_MATCHED:
                pending_completion = candidate
                completed_transaction = candidate["transaction"]
                break

        try:
            if record.parse_errors:
                _LOGGER.warning(
                    "Growatt %s contains invalid values: %s",
                    record.message_id,
                    "; ".join(record.parse_errors),
                )

            # The charger can send the same completed session as both message types.
            dedup_key = record.dedup_key
            if dedup_key is not None and (
                dedup_key in coordinator._applied_session_record_keys
                or coordinator._last_session_record_key == dedup_key
            ):
                duplicate_session = build_unified_session(
                    completed_transaction,
                    session_records=(snapshot,),
                    charge_point_id=coordinator.charge_point_id,
                    source_instance_id=coordinator.source_instance_id,
                    time_zone=session_time_zone(coordinator),
                )
                effective_minutes = None
                if (
                    duplicate_session is not None
                    and duplicate_session["correlation"]["status"] == CORRELATION_MATCHED
                ):
                    effective_minutes = coordinator._pending_effective_charging_minutes.pop(
                        str(record.transaction_id),
                        None,
                    )
                if effective_minutes is not None:
                    coordinator.last_session_effective_charging_minutes = effective_minutes
                    coordinator.hass.async_create_task(coordinator.async_save_storage())
                _LOGGER.debug(
                    "Duplicate Growatt session record skipped (transaction=%s)",
                    record.transaction_id,
                )
                coordinator.async_set_updated_data(True)
                return

            energy_kwh = record.energy_kwh
            cost = record.cost
            if energy_kwh is None or cost is None:
                _LOGGER.warning(
                    "Growatt %s retained but not applied because energy or cost is invalid",
                    record.message_id,
                )
                coordinator.async_set_updated_data(True)
                return

            if dedup_key is not None:
                coordinator._last_session_record_key = dedup_key
                coordinator._applied_session_record_keys.append(dedup_key)

            start_str = record.start_time
            end_str = record.end_time
            zone = session_time_zone(coordinator)
            started_at = utc_instant(start_str, zone)
            ended_at = utc_instant(end_str, zone)
            duration_minutes = (
                round((ended_at - started_at).total_seconds() / 60, 1)
                if started_at is not None and ended_at is not None and ended_at >= started_at
                else None
            )
            session = build_unified_session(
                completed_transaction,
                meter_values=coordinator.last_meter_values,
                session_records=(snapshot,),
                charge_point_id=coordinator.charge_point_id,
                source_instance_id=coordinator.source_instance_id,
                time_zone=session_time_zone(coordinator),
            )
            matched = (
                session is not None and session["correlation"]["status"] == CORRELATION_MATCHED
            )
            effective_minutes = (
                coordinator._pending_effective_charging_minutes.pop(
                    str(record.transaction_id),
                    None,
                )
                if matched
                else None
            )
            # A late vendor record may belong to a different transaction.
            # Keep its own identity; attaching the latest OCPP metadata would invent
            # an RFID identifier, event history or accounting allocation for it.
            if not matched:
                session = build_unified_session(
                    None,
                    session_records=(snapshot,),
                    charge_point_id=coordinator.charge_point_id,
                    source_instance_id=coordinator.source_instance_id,
                    time_zone=session_time_zone(coordinator),
                )
            identity = session["identity"]
            start_request = ((completed_transaction or {}).get("start") or {}).get("request") or {}
            authorized_identifier = start_request.get("id_tag") if matched else None
            events = merge_growatt_record_events(
                (completed_transaction or {}).get("events", []) if matched else [],
                plug_time=record.plug_time,
                start_time=record.start_time,
                end_time=record.end_time,
                unplug_time=record.unplug_time,
                time_zone=zone,
            )
            if matched and isinstance(completed_transaction, dict):
                completed_transaction["session_id"] = identity["session_id"]
                completed_transaction["events"] = list(events)

            coordinator.last_session_energy = energy_kwh
            coordinator.last_session_cost = cost
            coordinator.last_session_start = start_str
            coordinator.last_session_end = end_str
            coordinator.last_session_plug_time = record.plug_time
            coordinator.last_session_unplug_time = record.unplug_time
            coordinator.last_session_duration_minutes = duration_minutes
            coordinator.last_session_effective_charging_minutes = effective_minutes
            coordinator.last_session_id = identity["session_id"]
            coordinator.last_session_source = identity["session_source"]
            coordinator.last_session_transaction_id = record.transaction_id
            coordinator.last_session_charge_mode = record.charge_mode
            coordinator.last_session_work_mode = record.work_mode

            coordinator.total_energy_charged += energy_kwh
            accounting = (
                SessionAccumulator.from_dict(pending_completion.get("accounting"))
                if matched and pending_completion is not None
                else coordinator.last_site_accounting
                if matched
                and coordinator.last_site_accounting
                and str(record.transaction_id) == coordinator.last_site_accounting.transaction_id
                else None
            )
            if accounting is not None:
                accounting.reconcile(energy_kwh)
                coordinator.site_accounting_totals["energy_kwh"] += energy_kwh
                for key in (
                    "direct_solar",
                    "direct_grid",
                    "battery_unknown",
                    "unknown",
                ):
                    coordinator.site_accounting_totals[f"{key}_kwh"] += accounting.buckets[key]
                if accounting.cost_covered:
                    coordinator.site_accounting_totals["effective_grid_cost"] += (
                        accounting.effective_grid_cost
                    )

            _LOGGER.info(
                "%s: energy=%.3f kWh, cost=%.2f, duration=%s min, total=%.3f kWh",
                record.message_id,
                energy_kwh,
                cost,
                f"{duration_minutes:.1f}" if duration_minutes is not None else "unknown",
                coordinator.total_energy_charged,
            )

            # CSV logging via __init__.py helper
            append_fn = coordinator.runtime_data.get("append_session_to_csv")
            if append_fn:
                session_row = {
                    "timestamp": coordinator.now(),
                    "charger_id": coordinator.charge_point_id or "",
                    "source_instance_id": coordinator.source_instance_id or "",
                    "location": coordinator.location,
                    # Identity above uses the original reported times. Store new
                    # history instants explicitly so later clock settings cannot
                    # reinterpret them, while retaining the raw vendor record.
                    "start_time": utc_timestamp(start_str, zone) or start_str,
                    "end_time": utc_timestamp(end_str, zone) or end_str,
                    "energy_kwh": round(energy_kwh, 3),
                    "cost": round(cost, 2),
                    "duration_minutes": duration_minutes if duration_minutes is not None else "",
                    "effective_charging_minutes": (
                        effective_minutes if effective_minutes is not None else ""
                    ),
                    "transaction_id": record.transaction_id,
                    "session_id": coordinator.last_session_id,
                    "session_source": coordinator.last_session_source,
                    "authorized_identifier": authorized_identifier or "",
                    "authorized_alias": ((completed_transaction or {}).get("id_tag_alias") or "")
                    if matched
                    else "",
                    **(accounting.as_session_dict() if accounting else {"green_energy_kwh": ""}),
                    "power_curve": json.dumps(
                        (completed_transaction or {}).get("power_curve", []) if matched else [],
                        separators=(",", ":"),
                    ),
                    "site_house_load_source": (completed_transaction or {}).get(
                        "site_house_load_source", ""
                    )
                    if matched
                    else "",
                    **{
                        key: json.dumps(curve, separators=(",", ":"))
                        for key, curve in context_curves(
                            completed_transaction if matched else {}
                        ).items()
                    },
                    "events": json.dumps(events, separators=(",", ":")),
                }
                self.outbox.enqueue(session_row)
                coordinator.hass.async_create_task(self.async_flush_pending())
                if (
                    accounting is not None
                    and coordinator.last_site_accounting is not None
                    and coordinator.last_site_accounting.transaction_id == accounting.transaction_id
                ):
                    coordinator.last_site_accounting = None

            if pending_completion is not None:
                self.pending_completions.remove(pending_completion)
            coordinator.hass.async_create_task(coordinator.async_save_storage())
            coordinator.async_set_updated_data(True)

        except (ValueError, TypeError, KeyError) as exc:
            _LOGGER.warning(
                "Failed to process Growatt %s: %s",
                record.message_id,
                exc,
            )
