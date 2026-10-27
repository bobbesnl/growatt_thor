import logging
import json
import re
from datetime import datetime, time, timezone
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
import asyncio

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.storage import Store

from .sessions.active_state import ActiveSessionState
from .sessions.runtime import SessionLifecycle
from .charging.authorization import LocalAuthorization
from .sessions.duration import EffectiveChargingTracker
from .sessions.correlation import CORRELATION_MATCHED, build_unified_session
from .charging.controls import transaction_state_is_active
from .charging.faults import (
    ChargerFault,
    fault_from_data_transfer,
    fault_from_status_notification,
)
from .configuration.values import (
    ConfigurationValue,
    configuration_entity_state,
    configuration_numeric_value,
    configuration_value_from_item,
    merge_configuration_values,
    normalize_unknown_configuration_keys,
    parse_time_sharing_price,
)
from .configuration.writes import (
    ConfigurationWriteStatus,
    ConfigurationWriteState,
    acknowledge_configuration_write,
    begin_configuration_write,
    configuration_write_is_current,
    confirm_configuration_writes,
    mark_configuration_write,
)
from .const import DEFAULT_POLL_INTERVAL, DOMAIN
from .energy.sources import BATTERY_POSITIVE_DISCHARGE
from .energy.accounting_runtime import SessionAccumulator, parse_at, site_inputs
from .ocpp.external_meter import (
    external_meter_health,
    parse_external_meter_data,
    status_clears_external_meter_fault,
    status_reports_external_meter_fault,
)
from .ocpp.meter_samples import charging_power_curve_point, meter_time_zone, parse_meter_values
from .ocpp.diagnostics import create_ocpp_snapshot
from .ocpp.status import normalize_ocpp_status
from .charging.pv_linkage import (
    PvBoostMode,
    PvLinkageApplyResult,
    PvLinkageDraft,
    draft_matches_reported,
    parse_manual_period,
)
from .sessions.records import GrowattSessionRecord
from .sessions.events import (
    SessionEventTracker,
    append_session_event,
    merge_growatt_record_events,
    session_event,
)
from .sessions.state import LastSessionState, normalize_record_key
from .sessions.series import SESSION_CURVE_POINT_LIMIT, downsample_curve
from .sessions.transaction_ids import TransactionIdAllocator
from .runtime.charger_write_queue import ChargerWriteQueue
from .runtime.write_queue import (
    ChargerCommandHandle,
    ChargerCommandResult,
    ChargerWriteQueuePolicy,
    DEFAULT_WRITE_POLICY,
)

_LOGGER = logging.getLogger(__name__)

# Shared storage file used before per-entry storage existed. It is only read
# once, to seed a config entry that has no storage file of its own yet.
STORAGE_KEY = "growatt_thor_statistics"
STORAGE_VERSION = 1

# OCPP statuses in which the charger delivers energy. In every other status
# the last MeterValues sample is stale, so live power and current go to 0.
LIVE_POWER_STATUSES = frozenset({"charging"})


def storage_key_for_entry(source_instance_id) -> str:
    """Return the storage key of one config entry."""
    if not source_instance_id:
        return STORAGE_KEY
    return f"{STORAGE_KEY}_{source_instance_id}"


class GrowattCoordinator(DataUpdateCoordinator):
    """Coordinator for Growatt THOR OCPP data."""

    def __init__(self, hass, source_instance_id=None, seed_from_legacy=True):
        super().__init__(hass, _LOGGER, name="Growatt THOR Coordinator")

        self.sessions = SessionLifecycle(self)
        storage_key = storage_key_for_entry(source_instance_id)
        self._store = Store(hass, STORAGE_VERSION, storage_key)
        self._legacy_store = (
            Store(hass, STORAGE_VERSION, STORAGE_KEY)
            if seed_from_legacy and storage_key != STORAGE_KEY
            else None
        )
        self.source_instance_id = source_instance_id
        # This entry's runtime mapping (see runtime_ownership).  Setup replaces
        # it with the mapping registered under hass.data[DOMAIN][entry_id];
        # the active OCPP connection and the poll pause live here, never in a
        # domain-global slot shared with another charger.
        self.runtime_data = {}
        self._transaction_id_allocator = TransactionIdAllocator()
        self._transaction_id_lock = asyncio.Lock()

        self.charge_point_id = None
        self.status = None
        self.connected = False
        self.connection_started_at = None
        self.last_message_at = None
        self.last_message_action = None
        self.last_heartbeat_at = None
        self.transaction_id = None
        self.charging_target_request = None
        self.id_tag = None
        self.authorization = LocalAuthorization()

        # Latest normalized OCPP requests retained for HA diagnostics.
        self.boot_notification = None
        self.last_status_notification = None
        self.last_charger_fault: ChargerFault | None = None
        self.last_meter_values = None
        self.active_transaction = None
        self.last_completed_transaction = None
        self.last_current_record = None
        self.last_frozen_record = None
        self.effective_charging = EffectiveChargingTracker()
        self._pending_effective_charging_minutes: dict[str, float] = {}
        self._active_power_curve: list[list[object]] = []
        self._session_event_tracker: SessionEventTracker | None = None
        self._pending_plugged_event: dict[str, str] | None = None
        self._restored_active_session = False
        self.site_accounting_options = {}
        self.last_energy_stop = None
        self.site_accounting: SessionAccumulator | None = None
        self.last_site_accounting: SessionAccumulator | None = None
        self.site_accounting_totals = {
            "energy_kwh": 0.0,
            "direct_solar_kwh": 0.0,
            "direct_grid_kwh": 0.0,
            "battery_unknown_kwh": 0.0,
            "unknown_kwh": 0.0,
            "effective_grid_cost": 0.0,
        }

        # ── Totaal ─────────────────────────
        self.power = None        # W
        self.energy = None       # Wh

        # ── Fase-specifiek ─────────────────
        self.currents = {}       # {"L1": A, "L2": A, "L3": A}
        self.voltages = {}       # {"L1": V, "L2": V, "L3": V}
        self.phase_power = {}    # {"L1": W, "L2": W, "L3": W}

        self.temperature = None  # °C

        # ── Config (Growatt) ───────────────
        self.max_current = None
        self._external_limit_power = 10.0
        self.external_limit_power_enable = None
        self.charger_mode = None
        self.server_url = None
        self.lcd_close_enable = None
        self.location = ""
        self.battery_power_entity = None
        self.battery_power_sign = BATTERY_POSITIVE_DISCHARGE

        # Auto charge times (Thor values)
        self.auto_charge_start_time = None
        self.auto_charge_stop_time = None

        # Auto charge times (pending UI values)
        self.auto_charge_start_time_pending = None
        self.auto_charge_stop_time_pending = None

        # ── Electricity price ──────────────
        self.electricity_price = None  # Currency per kWh, parsed from G_TimeSharingPrice

        # Last-known raw and normalized GetConfiguration values.
        self.configuration_values: dict[str, ConfigurationValue] = {}
        self.unknown_configuration_keys: tuple[str, ...] = ()
        self.configuration_writes: dict[str, ConfigurationWriteState] = {}
        self.last_command_result: ChargerCommandResult | None = None

        # Local compound PV Linkage draft. It is sent only by the Apply button.
        self.pv_boost_mode_draft: PvBoostMode | None = None
        self.pv_manual_start_draft: time | None = None
        self.pv_manual_end_draft: time | None = None
        self.pv_smart_finish_draft: time | None = None
        self.pv_smart_target_energy_draft: float | None = None
        self.pv_linkage_draft_dirty = False
        self.pv_linkage_apply_result: PvLinkageApplyResult | None = None

        # ── Last session ─────────────────
        self.last_session_energy = None           # kWh
        self.last_session_cost = None             # float
        self.last_session_start = None            # str
        self.last_session_end = None              # str
        self.last_session_plug_time = None        # str
        self.last_session_unplug_time = None      # str
        self.last_session_duration_minutes = None  # float
        self.last_session_effective_charging_minutes = None  # float
        self.last_session_id = None               # str
        self.last_session_source = None           # str
        self.last_session_transaction_id = None   # str
        self.last_session_charge_mode = None      # str
        self.last_session_work_mode = None        # str
        self._last_session_record_key = None
        self._applied_session_record_keys = deque(maxlen=50)
        self.dashboard_sessions = {
            "items": [], "total_energy_kwh": 0.0, "total_cost": 0.0,
            "total_green_energy_kwh": None, "total_count": 0,
        }

        # ── Cumulatief totaal (persistent) ─
        self.total_energy_charged = 0.0           # kWh

        # ── External meter (grid connection) ───
        self.grid_power = None
        self.grid_voltages = {}
        self.grid_currents = {}
        self.external_meter_used = None
        self.external_meter_wring = None
        self.external_meter_last_updated_at = None
        self.external_meter_poll_interval = DEFAULT_POLL_INTERVAL
        self.external_meter_faulted = False
        self.external_meter_fault_connector_id = None
        self.external_meter_fault_error_code = None
        self.external_meter_fault_info = None
        self.meterval_consecutive_timeouts = 0

        self._connection_changed = asyncio.Event()
        self.write_queue = ChargerWriteQueue(self, self._connection_changed)
        self._shutting_down = False
        self._configuration_refresh_task = None
        self._auto_charge_schedule_task = None

    # ─────────────────────────────
    # PERSISTENT STORAGE
    # ─────────────────────────────

    async def async_load_storage(self):
        """Load persistent statistics from HA storage."""
        data = await self._store.async_load()
        seeded_from_legacy = False
        legacy_store = getattr(self, "_legacy_store", None)
        if not data and legacy_store is not None:
            data = await legacy_store.async_load()
            seeded_from_legacy = bool(data)
            if seeded_from_legacy:
                _LOGGER.info(
                    "📦 No storage for this config entry yet; seeding it "
                    "once from the shared legacy storage file"
                )
        if data:
            from .energy.stop_guard import restore_stop_report
            self.last_energy_stop = restore_stop_report(data.get("last_energy_stop"))
            self.sessions.outbox.restore(data.get("pending_session_rows"))
            self.total_energy_charged = float(data.get("total_energy_charged", 0.0))
            self._transaction_id_allocator.restore(
                data.get("next_transaction_id", 1)
            )
            self._restore_last_session_state(
                LastSessionState.from_dict(data.get("last_session"))
            )
            stored_keys = data.get("applied_session_record_keys", [])
            if isinstance(stored_keys, list):
                for value in stored_keys[-50:]:
                    key = normalize_record_key(value)
                    if key is not None and key not in self._applied_session_record_keys:
                        self._applied_session_record_keys.append(key)
            if self._last_session_record_key is not None and self._last_session_record_key not in self._applied_session_record_keys:
                self._applied_session_record_keys.append(self._last_session_record_key)
            self.last_charger_fault = ChargerFault.from_dict(
                data.get("last_charger_fault")
            )
            self.effective_charging = EffectiveChargingTracker.from_dict(
                data.get("active_effective_charging")
            )
            active_session = ActiveSessionState.from_dict(
                data.get("active_session")
            )
            if active_session.transaction_id is None:
                # Migration from stores written before the active dashboard
                # row was persisted. The effective tracker still provides an
                # honest transaction identity and last observed energy value.
                active_session = ActiveSessionState(
                    transaction_id=self.effective_charging.transaction_id,
                    energy_wh=self.effective_charging.last_energy_wh,
                )
            self._restore_active_session_state(active_session)
            self.site_accounting = SessionAccumulator.from_dict(
                data.get("active_site_accounting")
            )
            self.last_site_accounting = SessionAccumulator.from_dict(
                data.get("pending_site_accounting")
            )
            stored_totals = data.get("site_accounting_totals")
            if isinstance(stored_totals, dict):
                for key in self.site_accounting_totals:
                    try:
                        value = float(stored_totals.get(key, 0))
                    except (TypeError, ValueError):
                        continue
                    if value == value and (value >= 0 or key == "effective_grid_cost"):
                        self.site_accounting_totals[key] = value
            pending_effective = data.get("pending_effective_charging_minutes")
            if isinstance(pending_effective, dict):
                for key, value in pending_effective.items():
                    try:
                        self._pending_effective_charging_minutes[str(key)] = float(
                            value
                        )
                    except (TypeError, ValueError):
                        continue
            self.sessions.restore_completions(data.get("pending_completed_sessions"))
            _LOGGER.info(
                "📦 Loaded from storage: total_energy_charged=%.3f kWh, "
                "next_transaction_id=%d, last_session_transaction_id=%s",
                self.total_energy_charged,
                self._transaction_id_allocator.next_transaction_id,
                self.last_session_transaction_id,
            )
            if seeded_from_legacy:
                # Pin the seeded values to this entry's own file, so later
                # restarts no longer depend on the shared legacy file.
                await self.async_save_storage()
        else:
            _LOGGER.info("📦 No persistent storage found, starting fresh")

    async def async_save_storage(self):
        """Save persistent statistics to HA storage."""
        await self._store.async_save(self._storage_data())
        _LOGGER.debug(
            "💾 Saved to storage: total_energy_charged=%.3f kWh, "
            "next_transaction_id=%d",
            self.total_energy_charged,
            self._transaction_id_allocator.next_transaction_id,
        )

    def _storage_data(self) -> dict[str, object]:
        """Build the current JSON-safe persistent payload."""
        active_session = self._active_session_state()
        return {
            "pending_session_rows": self.sessions.outbox.snapshot(),
            "pending_completed_sessions": self.sessions.pending_completions,
            "last_energy_stop": self.last_energy_stop,
            "total_energy_charged": self.total_energy_charged,
            "next_transaction_id": self._transaction_id_allocator.next_transaction_id,
            "last_session": self._last_session_state().as_dict(),
            "applied_session_record_keys": [list(key) for key in self._applied_session_record_keys],
            "last_charger_fault": (
                self.last_charger_fault.as_dict()
                if self.last_charger_fault is not None
                else None
            ),
            "active_effective_charging": self.effective_charging.as_dict(),
            "active_session": (
                active_session.as_dict()
                if active_session is not None
                else None
            ),
            "active_site_accounting": (
                self.site_accounting.as_dict() if self.site_accounting else None
            ),
            "pending_site_accounting": (
                self.last_site_accounting.as_dict() if self.last_site_accounting else None
            ),
            "site_accounting_totals": dict(self.site_accounting_totals),
            "pending_effective_charging_minutes": dict(
                self._pending_effective_charging_minutes
            ),
        }

    def _active_session_state(self) -> ActiveSessionState | None:
        """Delegate this transition to the session lifecycle."""
        return self.sessions._active_session_state()

    def _restore_active_session_state(self, state: ActiveSessionState) -> None:
        """Delegate this transition to the session lifecycle."""
        return self.sessions._restore_active_session_state(state)

    def _discard_unconfirmed_restored_session(self) -> None:
        """Delegate this transition to the session lifecycle."""
        return self.sessions._discard_unconfirmed_restored_session()

    def _schedule_storage_save(self) -> None:
        """Coalesce frequent MeterValues persistence into one delayed write."""
        self._store.async_delay_save(self._storage_data, 60)

    async def async_allocate_transaction_id(self) -> int:
        """Allocate and persist the next local OCPP transaction ID."""
        async with self._transaction_id_lock:
            transaction_id = self._transaction_id_allocator.allocate()
            await self.async_save_storage()
            _LOGGER.debug(
                "Allocated local OCPP transaction ID: %d",
                transaction_id,
            )
            return transaction_id

    def _last_session_state(self) -> LastSessionState:
        """Build the normalized persistent last-session summary."""
        return LastSessionState(
            energy_kwh=self.last_session_energy,
            cost=self.last_session_cost,
            start_time=self.last_session_start,
            end_time=self.last_session_end,
            plug_time=self.last_session_plug_time,
            unplug_time=self.last_session_unplug_time,
            duration_minutes=self.last_session_duration_minutes,
            effective_charging_minutes=(
                self.last_session_effective_charging_minutes
            ),
            session_id=self.last_session_id,
            session_source=self.last_session_source,
            transaction_id=self.last_session_transaction_id,
            charge_mode=self.last_session_charge_mode,
            work_mode=self.last_session_work_mode,
            record_key=self._last_session_record_key,
        )

    def _restore_last_session_state(self, state: LastSessionState) -> None:
        """Restore existing entity backing values from persistent storage."""
        self.last_session_energy = state.energy_kwh
        self.last_session_cost = state.cost
        self.last_session_start = state.start_time
        self.last_session_end = state.end_time
        self.last_session_plug_time = state.plug_time
        self.last_session_unplug_time = state.unplug_time
        self.last_session_duration_minutes = state.duration_minutes
        self.last_session_effective_charging_minutes = (
            state.effective_charging_minutes
        )
        self.last_session_id = state.session_id
        self.last_session_source = state.session_source
        self.last_session_transaction_id = state.transaction_id
        self.last_session_charge_mode = state.charge_mode
        self.last_session_work_mode = state.work_mode
        self._last_session_record_key = state.record_key

    # ─────────────────────────────
    # WRITE QUEUE METHODS
    # ─────────────────────────────

    async def queue_write(
        self,
        write_func,
        *args,
        dedupe_key=None,
        priority=False,
        rate_limited=True,
        command_name=None,
        requires_connection=False,
        configuration_key=None,
        configuration_generation=None,
        policy: ChargerWriteQueuePolicy = DEFAULT_WRITE_POLICY,
        revalidate=None,
        on_unsent=None,
        **kwargs,
    ) -> ChargerCommandHandle:
        """Delegate charger intent to this entry's queue owner."""
        return await self.write_queue.enqueue(
            write_func, *args, dedupe_key=dedupe_key, priority=priority,
            rate_limited=rate_limited, command_name=command_name,
            requires_connection=requires_connection, configuration_key=configuration_key,
            configuration_generation=configuration_generation, policy=policy,
            revalidate=revalidate, on_unsent=on_unsent, **kwargs,
        )

    def cancel_queued_writes(self, *, dedupe_key: str, command_name: str | None = None, reason: str) -> int:
        return self.write_queue.cancel(dedupe_key=dedupe_key, command_name=command_name, reason=reason)

    @property
    def has_pending_charger_writes(self) -> bool:
        return self.write_queue.has_pending

    def publish_write_result(self, result: ChargerCommandResult) -> None:
        self.last_command_result = result
        self.async_set_updated_data(True)

    # ─────────────────────────────
    # 🔑 LOAD BALANCING PROPERTY
    # ─────────────────────────────

    @property
    def external_limit_power(self):
        """Return current load balancing limit (kW)."""
        return self._external_limit_power

    @external_limit_power.setter
    def external_limit_power(self, value):
        """Update load balancing limit."""
        self._external_limit_power = float(value)
        _LOGGER.debug("Load balancing limit updated to: %.1f kW", self._external_limit_power)

    # ─────────────────────────────
    # Utility methods
    # ─────────────────────────────

    def now(self) -> str:
        """Return current UTC timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    @property
    def transaction_is_active(self) -> bool:
        """Return whether any retained OCPP state indicates an active charge."""
        return transaction_state_is_active(
            active_transaction=self.active_transaction,
            transaction_id=self.transaction_id,
            status=self.status,
        )

    def set_charge_point(self, cp_id):
        """Set charge point ID and notify sensors."""
        if persist := self.runtime_data.get("persist_charger_identity"):
            persist(cp_id)
        self.charge_point_id = cp_id
        if refresh := self.runtime_data.get("refresh_dashboard"):
            self.hass.async_create_task(refresh())
        self.connected = True
        self.connection_started_at = self.now()
        self.last_message_at = self.connection_started_at
        self.last_message_action = "WebSocketConnect"
        self.last_heartbeat_at = None
        self._connection_changed.set()
        _LOGGER.info("Charge point connected: %s", cp_id)
        self.async_set_updated_data(True)

    def update_configuration_value(self, key: str, raw_value: str) -> None:
        """Update one acknowledged configuration value without dropping metadata."""
        previous = self.configuration_values.get(key)
        value = configuration_value_from_item(
            {
                "key": key,
                "value": raw_value,
                "readonly": previous.readonly if previous is not None else False,
            }
        )
        if value is None:
            return
        self.configuration_values[key] = value
        self.async_set_updated_data(True)

    def begin_configuration_write(self, key: str, raw_value: str) -> int:
        """Track a configuration write and return its per-key generation."""
        self.configuration_writes = begin_configuration_write(
            self.configuration_writes,
            key=key,
            raw_value=raw_value,
            requested_at=self.now(),
        )
        self.async_set_updated_data(True)
        return self.configuration_writes[key].generation

    def configuration_write_is_current(
        self,
        key: str,
        generation: int,
    ) -> bool:
        """Return whether a callback still owns the latest intent for a key."""
        return configuration_write_is_current(
            self.configuration_writes,
            key=key,
            generation=generation,
        )

    def acknowledge_configuration_write(
        self,
        key: str,
        *,
        generation: int,
        accepted: bool,
        result: object,
    ) -> bool:
        """Retain a current OCPP result; ignore a superseded response."""
        # Example: 10 A was sent, then 16 A was requested before its reply.
        # The 10 A acknowledgement is real, but cannot confirm the newer 16 A intent.
        outcome_is_current = self.configuration_write_is_current(key, generation)
        if not outcome_is_current:
            _LOGGER.info(
                "Ignoring superseded ChangeConfiguration result for %s "
                "(generation %d)",
                key,
                generation,
            )
        result_value = result.value if hasattr(result, "value") else str(result)
        self.configuration_writes = acknowledge_configuration_write(
            self.configuration_writes,
            key=key,
            generation=generation,
            accepted=accepted,
            result=result_value,
        )
        self.async_set_updated_data(True)
        return outcome_is_current

    def mark_configuration_write(
        self,
        key: str,
        status: ConfigurationWriteStatus,
        *,
        generation: int,
        result: str | None = None,
    ) -> bool:
        """Retain a current non-acknowledgement outcome."""
        outcome_is_current = self.configuration_write_is_current(key, generation)
        if not outcome_is_current:
            _LOGGER.info(
                "Ignoring superseded %s outcome for %s (generation %d)",
                status.value,
                key,
                generation,
            )
        self.configuration_writes = mark_configuration_write(
            self.configuration_writes,
            key=key,
            generation=generation,
            status=status,
            result=result,
        )
        self.async_set_updated_data(True)
        return outcome_is_current

    def schedule_configuration_refresh(self, *, delay: float = 20.0):
        """Coalesce post-write readbacks into one reconnect-safe task.

        Historically each accepted write slept for exactly the same 20 seconds
        as the queue rate limit.  The readback and the next write therefore woke
        together and competed for the OCPP connection.  A single shared task
        now waits until all queued writes have finished, then reads once from
        whichever connection is current at that time.
        """
        if (
            self._configuration_refresh_task is not None
            and not self._configuration_refresh_task.done()
        ):
            return self._configuration_refresh_task

        self._configuration_refresh_task = self.hass.async_create_task(
            self._delayed_configuration_refresh(delay)
        )
        return self._configuration_refresh_task

    def schedule_auto_charge_schedule_write(
        self,
        write_callback: Callable[[], Awaitable[None]],
        *,
        delay: float = 0.5,
    ):
        """Debounce the two entity edits that form one Auto Charge schedule.

        Home Assistant exposes start and stop as separate time entities, while
        the THOR accepts only one compound ``start-stop`` value.  Cancelling a
        still-sleeping task lets a typical back-to-back automation settle both
        entity values before a generation enters the charger write queue.
        """
        previous_task = self._auto_charge_schedule_task
        if previous_task is not None and not previous_task.done():
            previous_task.cancel()

        async def _delayed_write() -> None:
            try:
                await asyncio.sleep(delay)
                await write_callback()
            except asyncio.CancelledError:
                # Replacement and integration unload are expected cancellation
                # paths; neither represents a failed charger command.
                return
            except Exception:
                # The original HA entity action has already returned by the
                # time the debounce expires.  Preserve a visible traceback
                # instead of leaving an unobserved background-task exception.
                _LOGGER.exception(
                    "Failed to queue debounced Auto Charge schedule"
                )
            finally:
                if self._auto_charge_schedule_task is asyncio.current_task():
                    self._auto_charge_schedule_task = None

        task = self.hass.async_create_task(_delayed_write())
        self._auto_charge_schedule_task = task
        return task

    async def _delayed_configuration_refresh(self, delay: float) -> bool:
        """Wait for a safe request window and refresh reported configuration."""
        try:
            if delay > 0:
                await asyncio.sleep(delay)

            while True:
                await self.write_queue.idle.wait()

                charge_point = self.runtime_data.get("charge_point")
                if charge_point is None or not self.connected:
                    self._connection_changed.clear()
                    charge_point = self.runtime_data.get(
                        "charge_point"
                    )
                    if charge_point is None or not self.connected:
                        await self._connection_changed.wait()
                    continue

                # trigger_get_configuration repeats the pending-write check
                # while holding the per-connection request lock.  If a write
                # enters the queue in this small hand-off window, retry after
                # the queue is idle rather than racing it.
                completed = await charge_point.trigger_get_configuration(
                    skip_if_writes_pending=True
                )
                if completed:
                    return True
                # A false result can represent a 30-second timeout, a stale
                # connection, or a newly queued write.  Backing off avoids a
                # tight retry loop while the websocket cleanup catches up.
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            return False
        finally:
            self._configuration_refresh_task = None

    def pv_linkage_draft(self) -> PvLinkageDraft | None:
        """Return the current local PV Linkage draft when initialized."""
        if self.pv_boost_mode_draft is None:
            return None
        return PvLinkageDraft(
            boost_mode=self.pv_boost_mode_draft,
            manual_start=self.pv_manual_start_draft,
            manual_end=self.pv_manual_end_draft,
            smart_finish=self.pv_smart_finish_draft,
            smart_target_energy_kwh=self.pv_smart_target_energy_draft,
        )

    def update_pv_linkage_draft(self, **changes) -> None:
        """Update local compound-control fields without writing the charger."""
        for attribute, value in changes.items():
            if attribute not in {
                "pv_boost_mode_draft",
                "pv_manual_start_draft",
                "pv_manual_end_draft",
                "pv_smart_finish_draft",
                "pv_smart_target_energy_draft",
            }:
                raise ValueError(f"Unsupported PV Linkage draft field: {attribute}")
            setattr(self, attribute, value)
        draft = self.pv_linkage_draft()
        reported_mode = configuration_entity_state(
            "G_SolarBoost",
            self.configuration_values.get("G_SolarBoost"),
        )
        period_value = self.configuration_values.get("G_PeriodTime")
        self.pv_linkage_draft_dirty = not (
            draft is not None
            and draft_matches_reported(
                draft,
                reported_mode=(
                    reported_mode if isinstance(reported_mode, str) else None
                ),
                reported_period=(
                    period_value.raw_value
                    if period_value is not None
                    else None
                ),
            )
        )
        self.async_set_updated_data(True)

    def record_pv_linkage_apply_result(
        self,
        result: PvLinkageApplyResult,
    ) -> None:
        """Expose the latest logical compound-write outcome."""
        self.pv_linkage_apply_result = result
        self.async_set_updated_data(True)

    def mark_pv_linkage_draft_applied(
        self,
        expected_draft: PvLinkageDraft,
    ) -> bool:
        """Clear only the exact draft whose complete Apply succeeded.

        A user may edit the local draft while an older Apply is executing.  A
        successful acknowledgement for that older snapshot must not erase the
        newer unsent changes.
        """
        if self.pv_linkage_draft() != expected_draft:
            _LOGGER.info(
                "Keeping newer PV Linkage draft dirty after an older Apply"
            )
            return False
        self.pv_linkage_draft_dirty = False
        self.async_set_updated_data(True)
        return True

    def _initialize_pv_linkage_draft(self) -> bool:
        """Initialize an untouched draft from reported configuration values."""
        if self.pv_linkage_draft_dirty:
            return False

        updated = False
        reported_mode = configuration_entity_state(
            "G_SolarBoost",
            self.configuration_values.get("G_SolarBoost"),
        )
        if isinstance(reported_mode, str):
            try:
                mode = PvBoostMode(reported_mode)
            except ValueError:
                mode = None
            if mode is not None and self.pv_boost_mode_draft != mode:
                self.pv_boost_mode_draft = mode
                updated = True

        period_value = self.configuration_values.get("G_PeriodTime")
        period = parse_manual_period(
            period_value.raw_value if period_value is not None else None
        )
        if period is not None:
            start, end = period
            if self.pv_manual_start_draft != start:
                self.pv_manual_start_draft = start
                updated = True
            if self.pv_manual_end_draft != end:
                self.pv_manual_end_draft = end
                updated = True

        return updated

    def mark_connection_activity(self, action):
        """Record the latest inbound OCPP message."""
        timestamp = self.now()
        was_connected = self.connected
        self.connected = True
        if not was_connected:
            self._connection_changed.set()
        self.last_message_at = timestamp
        self.last_message_action = action
        if action == "Heartbeat":
            self.last_heartbeat_at = timestamp
        self.async_set_updated_data(True)

    def pause_polling_until(self, until):
        """Pause this entry's external meter poll until a monotonic time."""
        current = self.runtime_data.get("skip_polling_until", 0)
        self.runtime_data["skip_polling_until"] = max(current, until)

    def _reset_live_power(self):
        """Zero live power and current values that are no longer current.

        The THOR sends MeterValues only while it charges.  When charging ends
        with the cable still connected (SuspendedEV) no StopTransaction
        follows, so without this reset the last sample stays visible until
        the cable is unplugged.  Voltages are kept: the charger still sees
        mains voltage.
        """
        zero_phases = {"L1": 0, "L2": 0, "L3": 0}
        if (
            self.power == 0
            and self.phase_power == zero_phases
            and self.currents == zero_phases
        ):
            return False

        self.power = 0
        self.phase_power = dict(zero_phases)
        self.currents = dict(zero_phases)
        return True

    def set_disconnected(self):
        """Mark the active OCPP transport connection as disconnected."""
        was_connected = self.connected
        self.connected = False
        self._connection_changed.clear()
        if was_connected:
            _LOGGER.info("Charge point disconnected: %s", self.charge_point_id)
        if self._reset_live_power():
            _LOGGER.debug("Live power reset after disconnect")
        self.async_set_updated_data(True)

    async def async_shutdown(self) -> None:
        """Cancel coordinator-owned background work during integration unload."""
        self._shutting_down = True
        self.write_queue.begin_shutdown()
        tasks = (
            self._configuration_refresh_task,
            self._auto_charge_schedule_task,
        )
        for task in tasks:
            if task is not None and not task.done():
                task.cancel()
        await self.write_queue.async_shutdown()
        for task in tasks:
            if task is None or task.done():
                continue
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Flush the live-session snapshot before a config-entry reload or a
        # Core restart tears down the coordinator.
        if hasattr(self, "_store"):
            await self.sessions.async_flush_pending()
            await self.async_save_storage()

    def set_status(self, status):
        """Set charger status and notify sensors."""
        value = status.value if hasattr(status, "value") else str(status)

        if self.status != value:
            self.status = value
            _LOGGER.debug("Status changed to: %s", value)

        normalized = normalize_ocpp_status(value)
        if (
            normalized is not None
            and normalized not in LIVE_POWER_STATUSES
            and self._reset_live_power()
        ):
            _LOGGER.info("Status %s: live power reset to 0 W", value)

        self.async_set_updated_data(True)

    def record_boot_notification(self, payload):
        """Retain the latest BootNotification request."""
        self.boot_notification = create_ocpp_snapshot(self.now(), payload)
        self.async_set_updated_data(True)

    def record_status_notification(
        self,
        connector_id,
        status,
        error_code=None,
        **payload,
    ):
        """Retain the latest StatusNotification request and update its state."""
        request = {
            "connector_id": connector_id,
            "status": status,
            "error_code": error_code,
            **payload,
        }
        previous_status = normalize_ocpp_status(self.status)
        self.last_status_notification = create_ocpp_snapshot(self.now(), request)
        received_at = self.last_status_notification["received_at"]
        normalized_status = normalize_ocpp_status(status)
        if normalized_status in {"charging", "suspended_ev", "suspended_evse"}:
            self._restored_active_session = False
        elif normalized_status == "available":
            self._discard_unconfirmed_restored_session()
        if (
            normalized_status == "preparing"
            and previous_status in (None, "available", "idle")
        ):
            self._pending_plugged_event = session_event(
                "plugged_in", received_at, "ocpp", "derived"
            )
        elif normalized_status == "available":
            unplugged = session_event(
                "unplugged", received_at, "ocpp", "derived"
            )
            target = self.active_transaction or self.last_completed_transaction
            if isinstance(target, dict):
                events = target.setdefault("events", [])
                event_added = append_session_event(
                    events, unplugged, unique_type=True
                )
                session_id = target.get("session_id")
                update_fn = self.runtime_data.get(
                    "update_session_events_in_csv"
                )
                if event_added and session_id and update_fn:
                    self.hass.async_create_task(
                        update_fn(session_id, list(events))
                    )
            self._pending_plugged_event = None
        # Connector 0 describes the whole station, not the active EV session.
        # Use receipt time: this is when we observed the pause, not an inferred
        # final power sample or the unknown time at which the car became full.
        transaction = self.active_transaction
        tracker = self._session_event_tracker
        if transaction and tracker is not None and connector_id not in (None, 0):
            active_connector = transaction.get("start", {}).get("request", {}).get("connector_id")
            if active_connector in (None, connector_id) and tracker.observe_suspension(
                received_at, normalized_status
            ):
                self._schedule_storage_save()
        if normalize_ocpp_status(status) == "faulted":
            self.last_charger_fault = fault_from_status_notification(
                self.now(),
                connector_id,
                error_code,
                payload,
            )
            self._schedule_fault_storage_save()
        info = payload.get("info")
        if status_reports_external_meter_fault(error_code, info):
            self.external_meter_faulted = True
            self.external_meter_fault_connector_id = connector_id
            self.external_meter_fault_error_code = (
                error_code.value if hasattr(error_code, "value") else error_code
            )
            self.external_meter_fault_info = info
        elif (
            self.external_meter_faulted
            and status_clears_external_meter_fault(error_code)
            and connector_id == self.external_meter_fault_connector_id
        ):
            self.external_meter_faulted = False
            self.external_meter_fault_connector_id = None
            self.external_meter_fault_error_code = None
            self.external_meter_fault_info = None
        self.set_status(status)

    def process_fault_message(
        self,
        vendor_id: object,
        data: str,
    ) -> None:
        """Retain and merge a Growatt DataTransfer/faultmessage event."""
        self.last_charger_fault = fault_from_data_transfer(
            self.now(),
            vendor_id,
            data,
            self.last_charger_fault,
        )
        self._schedule_fault_storage_save()
        self.async_set_updated_data(True)

    @property
    def charger_is_faulted(self) -> bool:
        """Return whether the current OCPP charger status is Faulted."""
        return normalize_ocpp_status(self.status) == "faulted"

    def _schedule_fault_storage_save(self) -> None:
        """Coalesce paired StatusNotification/faultmessage storage writes."""
        self._store.async_delay_save(self._storage_data, 1)

    def start_transaction(
        self,
        transaction_id,
        id_tag=None,
        *,
        connector_id=None,
        meter_start=None,
        **payload,
    ):
        """Delegate this transition to the session lifecycle."""
        return self.sessions.start_transaction(transaction_id, id_tag, connector_id=connector_id, meter_start=meter_start, **payload)

    def stop_transaction(
        self,
        reason=None,
        *,
        transaction_id=None,
        meter_stop=None,
        **payload,
    ):
        """Delegate this transition to the session lifecycle."""
        return self.sessions.stop_transaction(reason, transaction_id=transaction_id, meter_stop=meter_stop, **payload)

    # ─────────────────────────────
    # MeterValues
    # ─────────────────────────────

    def process_meter_values(
        self,
        meter_values,
        *,
        connector_id=None,
        transaction_id=None,
    ):
        """Retain all MeterValues samples and update known live sensors."""
        if transaction_id is not None:
            active_id = self.transaction_id
            if active_id is None:
                # Reconnect recovery requires a charging observation; late
                # telemetry alone cannot resurrect an ended transaction.
                if normalize_ocpp_status(self.status) not in {"charging", "suspended_ev", "suspended_evse"}:
                    return
                self.transaction_id = transaction_id
                self._schedule_storage_save()
            elif str(transaction_id) != str(active_id):
                _LOGGER.info("Ignoring MeterValues for inactive transaction %s", transaction_id)
                return
        parsed_values = parse_meter_values(
            meter_values,
            time_zone=meter_time_zone(
                self.configuration_values,
                getattr(getattr(self.hass, "config", None), "time_zone", None),
            ),
        )
        self.last_meter_values = {
            "received_at": self.now(),
            "connector_id": connector_id,
            "transaction_id": transaction_id,
            "meter_values": [entry.as_dict() for entry in parsed_values],
        }
        received_at = parse_at(self.last_meter_values["received_at"])
        updated = False
        if self.site_accounting is not None and str(transaction_id or self.transaction_id) == self.site_accounting.transaction_id:
            accounting_updated = False
            for entry in parsed_values:
                at = parse_at(entry.timestamp)
                if at is None or received_at is None or at > received_at:
                    continue
                power_point = charging_power_curve_point(entry)
                if power_point is not None:
                    accounting_updated = self.site_accounting.observe_power_fallback(power_point[1], at) or accounting_updated
                for sample in entry.samples:
                    if sample.measurand != "Energy.Active.Import.Register" or sample.numeric_value is None or sample.phase is not None:
                        continue
                    # A long telemetry gap cannot be priced/classified from
                    # just the current site snapshot (including after upgrade).
                    previous_at = self.site_accounting.last_meter_at
                    max_gap = self._effective_meter_gap_seconds()
                    current_interval = (
                        previous_at is not None
                        and 0 <= (at - previous_at).total_seconds() <= max_gap
                        and 0 <= (received_at - at).total_seconds() <= max_gap
                    )
                    accounting_updated = self.site_accounting.observe(
                        meter_wh=sample.numeric_value,
                        at=at,
                        site_id=self.source_instance_id or "site",
                        charger_id=self.charge_point_id or "charger",
                        inputs=site_inputs(self, at, received_at=received_at) if current_interval else None,
                        context=sample.context,
                        unit=sample.unit,
                    ) or accounting_updated
            if accounting_updated:
                self.hass.async_create_task(self.async_save_storage())
        effective_transaction_id = (
            transaction_id
            if transaction_id is not None
            else self.transaction_id
        )
        if effective_transaction_id is not None:
            previous_transaction_id = self.effective_charging.transaction_id
            self.effective_charging.start(effective_transaction_id)
            effective_updated = (
                previous_transaction_id != self.effective_charging.transaction_id
            )
            max_gap_seconds = self._effective_meter_gap_seconds()
            for entry in parsed_values:
                effective_updated = (
                    self.effective_charging.observe(
                        entry,
                        max_gap_seconds=max_gap_seconds,
                    )
                    or effective_updated
                )
            if effective_updated:
                self._schedule_storage_save()

        live_power = self._live_power_follows_samples()
        ignored_live_samples = False

        for entry in parsed_values:
            for sample in entry.samples:
                value = sample.numeric_value
                if value is None:
                    _LOGGER.warning(
                        "Failed to parse MeterValues sample value %r for %s",
                        sample.raw_value,
                        sample.measurand,
                    )
                    continue

                if (
                    sample.measurand in ("Power.Active.Import", "Current.Import")
                    and not live_power
                ):
                    # Retained above in last_meter_values for diagnostics,
                    # but not shown as live: the charger reports that it is
                    # not delivering energy.
                    ignored_live_samples = True
                    continue

                if sample.measurand == "Energy.Active.Import.Register":
                    if sample.context == "Transaction.Begin":
                        _LOGGER.debug(
                            "Skipping transaction-begin energy sample: %.3f Wh",
                            value,
                        )
                    elif self.energy != value:
                        self.energy = value
                        updated = True

                elif sample.measurand == "Power.Active.Import":
                    effective_phase = sample.phase or "L1"
                    if self.phase_power.get(effective_phase) != value:
                        self.phase_power[effective_phase] = value
                        updated = True

                elif sample.measurand == "Current.Import":
                    effective_phase = sample.phase or "L1"
                    if self.currents.get(effective_phase) != value:
                        self.currents[effective_phase] = value
                        updated = True

                elif sample.measurand == "Voltage":
                    effective_phase = sample.phase or "L1"
                    if self.voltages.get(effective_phase) != value:
                        self.voltages[effective_phase] = value
                        updated = True

                elif sample.measurand == "Temperature":
                    if self.temperature != value:
                        self.temperature = value
                        updated = True

            if effective_transaction_id is not None:
                point = charging_power_curve_point(entry)
                if point is not None and (
                    not self._active_power_curve
                    or self._active_power_curve[-1][0] != point[0]
                ):
                    self._active_power_curve.append(point)
                    if len(self._active_power_curve) > SESSION_CURVE_POINT_LIMIT * 2:
                        self._active_power_curve = downsample_curve(
                            self._active_power_curve,
                            limit=SESSION_CURVE_POINT_LIMIT,
                            event_times=(
                                event.get("at")
                                for event in (
                                    self._session_event_tracker.events
                                    if self._session_event_tracker is not None
                                    else ()
                                )
                            ),
                        )
                    if self._session_event_tracker is not None:
                        self._session_event_tracker.observe_power(
                            point[0], point[1]
                        )
                    self._schedule_storage_save()

        if self.phase_power:
            total = sum(self.phase_power.values())
            if self.power != total:
                self.power = total
                updated = True

        if ignored_live_samples:
            _LOGGER.debug(
                "Ignoring live power and current from MeterValues while "
                "status is %s",
                self.status,
            )
        _LOGGER.debug(
            "Retained %d MeterValues entries%s",
            len(parsed_values),
            " and updated live sensors" if updated else "",
        )
        self.async_set_updated_data(True)

    def _live_power_follows_samples(self) -> bool:
        """Return whether MeterValues may update live power and current.

        Live power and current follow samples only while the charger reports
        Charging, or while no status is known yet.  In every other status the
        charger is not delivering energy, so a sample that arrives late (for
        example a MeterValues report after SuspendedEV) must not bring the
        last charging power back.  When the vehicle draws again the THOR
        reports Charging first, so valid measurements apply again at once.
        """
        normalized = normalize_ocpp_status(self.status)
        return normalized is None or normalized in LIVE_POWER_STATUSES

    def _effective_meter_gap_seconds(self) -> float:
        """Bound counted intervals using the charger-reported sample period."""
        for key in ("G_MeterValueInterval", "MeterValueSampleInterval"):
            value = self.configuration_values.get(key)
            if value is None:
                continue
            try:
                interval = float(value.parsed_value)
            except (TypeError, ValueError):
                continue
            if interval > 0:
                return max(30.0, interval * 3)
        return 180.0

    def record_stop_requested(self, *, reason="remote_stop") -> None:
        """Delegate this transition to the session lifecycle."""
        return self.sessions.record_stop_requested(reason=reason)

    # ─────────────────────────────
    # GetConfiguration verwerking
    # ─────────────────────────────

    def process_configuration(self, configuration: list, unknown_keys=()):
        """Process GetConfiguration response with TIER 1 error handling."""
        self.configuration_values, updated = merge_configuration_values(
            self.configuration_values,
            (item for item in configuration if isinstance(item, dict)),
        )

        normalized_unknown_keys = normalize_unknown_configuration_keys(unknown_keys)
        if self.unknown_configuration_keys != normalized_unknown_keys:
            self.unknown_configuration_keys = normalized_unknown_keys
            updated = True

        reported_values = {
            str(item["key"]): (
                None if item.get("value") is None else str(item.get("value"))
            )
            for item in configuration
            if isinstance(item, dict) and item.get("key")
        }
        confirmed_writes = confirm_configuration_writes(
            self.configuration_writes,
            reported_values,
            readback_at=self.now(),
        )
        if confirmed_writes != self.configuration_writes:
            self.configuration_writes = confirmed_writes
            updated = True

        if self._initialize_pv_linkage_draft():
            updated = True

        for item in configuration:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            raw = item.get("value")

            try:
                if key == "G_MaxCurrent":
                    value = configuration_numeric_value(
                        self.configuration_values.get(key)
                    )
                    if value is None:
                        continue
                    if self.max_current != value:
                        self.max_current = value
                        _LOGGER.debug("Config: MaxCurrent = %.1f A", value)
                        updated = True

                elif key == "G_ExternalLimitPower":
                    value = configuration_numeric_value(
                        self.configuration_values.get(key)
                    )
                    if value is None:
                        continue
                    if self.external_limit_power != value:
                        self.external_limit_power = value
                        _LOGGER.debug("Config: ExternalLimitPower = %.1f kW", value)
                        updated = True

                elif key == "G_ExternalLimitPowerEnable":
                    value = raw in ("1", "true", "True")
                    if self.external_limit_power_enable != value:
                        self.external_limit_power_enable = value
                        _LOGGER.debug("Config: ExternalLimitPowerEnable = %s", value)
                        updated = True

                elif key == "G_ChargerMode":
                    value = int(raw)
                    if self.charger_mode != value:
                        self.charger_mode = value
                        _LOGGER.debug("Config: ChargerMode = %d", value)
                        updated = True

                elif key == "G_ServerURL":
                    if self.server_url != raw:
                        self.server_url = raw
                        _LOGGER.debug("Config: ServerURL = %s", raw)
                        updated = True

                elif key == "G_AutoChargeTime":
                    if raw and "-" in raw:
                        start_str, stop_str = raw.split("-", 1)
                        try:
                            start_time = datetime.strptime(start_str.strip(), "%H:%M").time()
                            stop_time = datetime.strptime(stop_str.strip(), "%H:%M").time()

                            if self.auto_charge_start_time != start_time:
                                self.auto_charge_start_time = start_time
                                self.auto_charge_start_time_pending = start_time
                                _LOGGER.debug("Config: AutoChargeStartTime = %s", start_time)
                                updated = True

                            if self.auto_charge_stop_time != stop_time:
                                self.auto_charge_stop_time = stop_time
                                self.auto_charge_stop_time_pending = stop_time
                                _LOGGER.debug("Config: AutoChargeStopTime = %s", stop_time)
                                updated = True
                        except ValueError as exc:
                            _LOGGER.warning("Failed to parse G_AutoChargeTime '%s': %s", raw, exc)

                elif key == "G_LCDCloseEnable":
                    if self.lcd_close_enable != raw:
                        self.lcd_close_enable = raw
                        _LOGGER.debug("Config: LCDCloseEnable = %s", raw)
                        updated = True

                elif key == "G_TimeSharingPrice":
                    value = parse_time_sharing_price(raw)
                    if value is not None:
                        value = round(value, 2)
                        if self.electricity_price != value:
                            self.electricity_price = value
                            _LOGGER.debug("Config: G_TimeSharingPrice = %.2f per kWh", value)
                            updated = True
                    else:
                        _LOGGER.warning("Could not parse G_TimeSharingPrice from raw value: %s", raw)

            except (ValueError, TypeError) as exc:
                _LOGGER.warning("Failed to parse config key=%s value=%s: %s", key, raw, exc)
                continue
            except Exception as exc:
                _LOGGER.error("Unexpected error processing config key=%s: %s", key, exc, exc_info=True)
                continue

        if updated:
            self.async_set_updated_data(True)

    # ─────────────────────────────
    # Growatt session records
    # ─────────────────────────────

    def process_session_record(self, record: GrowattSessionRecord):
        """Delegate this transition to the session lifecycle."""
        return self.sessions.process_session_record(record)

    # ─────────────────────────────
    # Growatt external meter values
    # ─────────────────────────────

    @property
    def external_meter_health(self) -> str:
        """Return the effective external-meter communication state."""
        return external_meter_health(
            explicit_fault=self.external_meter_faulted,
            consecutive_timeouts=self.meterval_consecutive_timeouts,
            has_snapshot=self.external_meter_last_updated_at is not None,
        )

    @property
    def external_meter_ready_for_pv(self) -> bool:
        """Return whether entering a PV Linkage mode is currently safe."""
        return self.external_meter_health == "healthy"

    def record_external_meter_poll_timeout(self) -> None:
        """Record one missed external-meter response and refresh HA state."""
        self.meterval_consecutive_timeouts += 1
        self.async_set_updated_data(True)

    def reset_external_meter_poll_timeouts(self) -> None:
        """Clear communication timeouts after a valid meter response."""
        if self.meterval_consecutive_timeouts:
            self.meterval_consecutive_timeouts = 0

    def process_external_meter(self, data_str: str) -> bool:
        """Process external meter values from get_external_meterval DataTransfer."""
        try:
            snapshot = parse_external_meter_data(data_str)
            self.reset_external_meter_poll_timeouts()

            if self.external_meter_used != snapshot.used:
                self.external_meter_used = snapshot.used

            if self.external_meter_wring != snapshot.wring:
                self.external_meter_wring = snapshot.wring

            if self.grid_voltages != snapshot.voltages:
                self.grid_voltages = snapshot.voltages

            if self.grid_currents != snapshot.currents:
                self.grid_currents = snapshot.currents

            if self.grid_power != snapshot.power:
                self.grid_power = snapshot.power

            self.external_meter_last_updated_at = self.now()
            _LOGGER.debug(
                "External meter snapshot: used=%s wring=%s power=%s voltages=%s currents=%s",
                snapshot.used,
                snapshot.wring,
                snapshot.power,
                snapshot.voltages,
                snapshot.currents,
            )
            self.async_set_updated_data(True)
            return True

        except (ValueError, TypeError, KeyError) as exc:
            _LOGGER.warning("Failed to process external meter data '%s': %s", data_str, exc)
            return False
