from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable, Sequence
from datetime import UTC, datetime, time
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .charging.authorization import LocalAuthorization
from .charging.control_capabilities import (
    ChargingControl,
    control_write_block_reason,
    transaction_state_is_active,
)
from .charging.faults import ChargerFault
from .charging.pv_draft import PvLinkageDraftState
from .charging.pv_linkage import PvLinkageApplyResult, PvLinkageDraft
from .configuration.readback import ConfigurationReadback
from .configuration.values import ConfigurationValue, configuration_value_from_item
from .configuration.write_tracker import ConfigurationWriteTracker
from .configuration.writes import ConfigurationWriteState, ConfigurationWriteStatus
from .const import CONF_LOCATION, CONF_POLL_INTERVAL, CONFIGURATION_WRITE_SPACING_SECONDS
from .energy.options import CONF_BATTERY_POWER_ENTITY, CONF_BATTERY_POWER_SIGN
from .energy.session_accumulator import SessionAccumulator
from .energy.sources import BATTERY_POSITIVE_DISCHARGE
from .ocpp.external_meter_state import ExternalMeterState
from .ocpp.status import normalize_ocpp_status
from .runtime.charger_write_queue import ChargerWriteQueue
from .runtime.coordinator_storage import restore_storage_data, storage_data
from .runtime.entry import EntryRuntime
from .runtime.keys import (
    ACTIVE_CHARGE_POINT,
    ENERGY_STOP_GUARD,
    PERSIST_CHARGER_IDENTITY,
    REFRESH_DASHBOARD,
    SKIP_POLLING_UNTIL,
)
from .runtime.ocpp_ingest import OcppIngest
from .runtime.write_results import (
    DEFAULT_WRITE_POLICY,
    ChargerCommandHandle,
    ChargerCommandResult,
    ChargerWriteQueuePolicy,
    ChargerWriteResult,
)
from .sessions.active_state import ActiveTransaction
from .sessions.duration import EffectiveChargingTracker
from .sessions.hooks import TransactionHooks
from .sessions.records import GrowattSessionRecord
from .sessions.runtime import SessionLifecycle

# Re-exported for focused tests that build a coordinator from this module.
from .sessions.state import LastSessionState as LastSessionState
from .sessions.transaction_ids import TransactionIdAllocator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .ocpp.server import GrowattChargePoint
    from .targets.requests import TargetRecord


_LOGGER = logging.getLogger(__name__)

# Shared storage file used before per-entry storage existed. It is only read
# once, to seed a config entry that has no storage file of its own yet.
STORAGE_KEY = "growatt_thor_statistics"
STORAGE_VERSION = 1


def storage_key_for_entry(source_instance_id: str | None) -> str:
    """Return the storage key of one config entry."""
    if not source_instance_id:
        return STORAGE_KEY
    return f"{STORAGE_KEY}_{source_instance_id}"


if TYPE_CHECKING:
    _CoordinatorBase = DataUpdateCoordinator[bool]
else:
    _CoordinatorBase = DataUpdateCoordinator


class GrowattCoordinator(_CoordinatorBase):
    """Coordinator for Growatt THOR OCPP data."""

    def __init__(
        self,
        hass: HomeAssistant,
        source_instance_id: str | None = None,
        seed_from_legacy: bool = True,
    ) -> None:
        super().__init__(hass, _LOGGER, name="Growatt THOR Coordinator")

        self.sessions = SessionLifecycle(self)
        self.ingest = OcppIngest(self)
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
        self.runtime_data = EntryRuntime()
        self.external_meter = ExternalMeterState()
        self.pv_draft = PvLinkageDraftState()
        self._transaction_id_allocator = TransactionIdAllocator()
        self._transaction_id_lock = asyncio.Lock()

        self.charge_point_id: str | None = None
        self.status: str | None = None
        self.connected = False
        self.connection_started_at: str | None = None
        self.last_message_at: str | None = None
        self.last_message_action: str | None = None
        self.last_heartbeat_at: str | None = None
        self.transaction_id: int | str | None = None
        self.charging_target_request: TargetRecord | None = None
        self.transaction_hooks: TransactionHooks | None = None
        self.charging_target_pilot_enabled = False
        self.id_tag: str | None = None
        self.authorization = LocalAuthorization()

        # Latest normalized OCPP requests retained for HA diagnostics.
        self.boot_notification: dict[str, Any] | None = None
        self.last_status_notification: dict[str, Any] | None = None
        self.last_charger_fault: ChargerFault | None = None
        self.last_meter_values: dict[str, Any] | None = None
        self.active_transaction: ActiveTransaction | None = None
        self.last_completed_transaction: dict[str, Any] | None = None
        self.last_current_record: dict[str, Any] | None = None
        self.last_frozen_record: dict[str, Any] | None = None
        self.effective_charging = EffectiveChargingTracker()
        self.site_accounting_options: dict[str, Any] = {}
        self.last_energy_stop: dict[str, object] | None = None
        self.dashboard_command: dict[str, object] | None = None
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

        #  Totals
        self.power: float | None = None  # W
        self.energy: float | None = None  # Wh

        #  Per-phase values
        self.currents: dict[str, float] = {}  # {"L1": A, "L2": A, "L3": A}
        self.voltages: dict[str, float] = {}  # {"L1": V, "L2": V, "L3": V}
        self.phase_power: dict[str, float] = {}  # {"L1": W, "L2": W, "L3": W}

        self.temperature: float | None = None  # °C

        #  Config (Growatt)
        self.max_current: float | None = None
        self._external_limit_power = 10.0
        self.external_limit_power_enable: bool | None = None
        self.charger_mode: int | None = None
        self.server_url: str | None = None
        self.lcd_close_enable: str | None = None
        self.location = ""
        self.battery_power_entity: str | None = None
        self.battery_power_sign = BATTERY_POSITIVE_DISCHARGE

        # Auto charge times (Thor values)
        self.auto_charge_start_time: time | None = None
        self.auto_charge_stop_time: time | None = None

        # Auto charge times (pending UI values)
        self.auto_charge_start_time_pending: time | None = None
        self.auto_charge_stop_time_pending: time | None = None

        #  Electricity price
        self.electricity_price: float | None = (
            None  # Currency per kWh, parsed from G_TimeSharingPrice
        )

        # Last-known raw and normalized GetConfiguration values.
        self.configuration_values: dict[str, ConfigurationValue] = {}
        self.unknown_configuration_keys: tuple[str, ...] = ()
        self.configuration_write_tracker = ConfigurationWriteTracker(
            now=lambda: self.now(), notify=lambda: self.async_set_updated_data(True)
        )
        self.last_command_result: ChargerCommandResult | None = None

        self.dashboard_sessions: dict[str, Any] = {
            "items": [],
            "total_energy_kwh": 0.0,
            "total_cost": 0.0,
            "total_green_energy_kwh": None,
            "total_count": 0,
        }

        #  Persistent cumulative total
        self.total_energy_charged = 0.0  # kWh

        self._connection_changed = asyncio.Event()
        self.write_queue = ChargerWriteQueue(self, self._connection_changed)
        self._shutting_down = False
        self.configuration_readback = ConfigurationReadback(self, self._connection_changed)
        self._auto_charge_schedule_task: asyncio.Task[None] | None = None

    # PERSISTENT STORAGE

    async def async_load_storage(self) -> None:
        """Load persistent statistics from HA storage."""
        data = await self._store.async_load()
        seeded_from_legacy = False
        legacy_store = self._legacy_store
        if not data and legacy_store is not None:
            data = await legacy_store.async_load()
            seeded_from_legacy = bool(data)
            if seeded_from_legacy:
                _LOGGER.info(
                    "No storage for this config entry yet; seeding it "
                    "once from the shared legacy storage file"
                )
        if data:
            restore_storage_data(self, data)
            _LOGGER.info(
                "Loaded from storage: total_energy_charged=%.3f kWh, "
                "next_transaction_id=%d, last_session_transaction_id=%s",
                self.total_energy_charged,
                self._transaction_id_allocator.next_transaction_id,
                self.sessions.last_session.transaction_id,
            )
            if seeded_from_legacy:
                # Pin the seeded values to this entry's own file, so later
                # restarts no longer depend on the shared legacy file.
                await self.async_save_storage()
        else:
            _LOGGER.info("No persistent storage found, starting fresh")

    async def async_save_storage(self) -> None:
        """Save persistent statistics to HA storage."""
        await self._store.async_save(self._storage_data())
        _LOGGER.debug(
            "Saved to storage: total_energy_charged=%.3f kWh, next_transaction_id=%d",
            self.total_energy_charged,
            self._transaction_id_allocator.next_transaction_id,
        )

    def _storage_data(self) -> dict[str, object]:
        """Build the current JSON-safe persistent payload."""
        return storage_data(self)

    def schedule_storage_save(self) -> None:
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

    # WRITE QUEUE METHODS

    async def queue_write(
        self,
        write_func: Callable[..., Awaitable[Any]],
        *args: Any,
        dedupe_key: object | None = None,
        priority: bool = False,
        rate_limited: bool = True,
        command_name: str | None = None,
        requires_connection: bool = False,
        configuration_key: str | None = None,
        configuration_generation: int | None = None,
        policy: ChargerWriteQueuePolicy = DEFAULT_WRITE_POLICY,
        revalidate: Callable[[], str | None] | None = None,
        on_unsent: Callable[[ChargerWriteResult], None] | None = None,
        **kwargs: Any,
    ) -> ChargerCommandHandle:
        """Delegate charger intent to this entry's queue owner."""
        return await self.write_queue.enqueue(
            write_func,
            *args,
            dedupe_key=dedupe_key,
            priority=priority,
            rate_limited=rate_limited,
            command_name=command_name,
            requires_connection=requires_connection,
            configuration_key=configuration_key,
            configuration_generation=configuration_generation,
            policy=policy,
            revalidate=revalidate,
            on_unsent=on_unsent,
            **kwargs,
        )

    def cancel_queued_writes(
        self, *, dedupe_key: str, command_name: str | None = None, reason: str
    ) -> int:
        return self.write_queue.cancel(
            dedupe_key=dedupe_key, command_name=command_name, reason=reason
        )

    @property
    def has_pending_charger_writes(self) -> bool:
        return self.write_queue.has_pending

    def publish_write_result(self, result: ChargerCommandResult) -> None:
        self.last_command_result = result
        self.async_set_updated_data(True)

    # LOAD BALANCING PROPERTY

    @property
    def external_limit_power(self) -> float:
        """Return current load balancing limit (kW)."""
        return self._external_limit_power

    @external_limit_power.setter
    def external_limit_power(self, value: Any) -> None:
        """Update load balancing limit."""
        self._external_limit_power = float(value)
        _LOGGER.debug("Load balancing limit updated to: %.1f kW", self._external_limit_power)

    # Utility methods

    @property
    def charge_point(self) -> GrowattChargePoint | None:
        """Return the connection currently owned by this entry."""
        return self.runtime_data.get(ACTIVE_CHARGE_POINT)

    def now(self) -> str:
        """Return current UTC timestamp in ISO format."""
        return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    @property
    def transaction_is_active(self) -> bool:
        """Return whether any retained OCPP state indicates an active charge."""
        return transaction_state_is_active(
            active_transaction=self.active_transaction,
            transaction_id=self.transaction_id,
            status=self.status,
        )

    def set_charge_point(self, cp_id: str) -> None:
        """Set charge point ID and notify sensors."""
        if persist := self.runtime_data.get(PERSIST_CHARGER_IDENTITY):
            persist(cp_id)
        self.charge_point_id = cp_id
        if refresh := self.runtime_data.get(REFRESH_DASHBOARD):
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
        if key == "G_MaxCurrent":
            self.sessions.observe_context()
        self.async_set_updated_data(True)

    @property
    def configuration_writes(self) -> dict[str, ConfigurationWriteState]:
        """Per-key write state, owned by the configuration write tracker."""
        return self.configuration_write_tracker.writes

    def begin_configuration_write(self, key: str, raw_value: str) -> int:
        return self.configuration_write_tracker.begin(key, raw_value)

    def configuration_write_is_current(self, key: str, generation: int) -> bool:
        return self.configuration_write_tracker.is_current(key, generation)

    def acknowledge_configuration_write(
        self, key: str, *, generation: int, accepted: bool, result: object
    ) -> bool:
        return self.configuration_write_tracker.acknowledge(
            key, generation=generation, accepted=accepted, result=result
        )

    def mark_configuration_write(
        self,
        key: str,
        status: ConfigurationWriteStatus,
        *,
        generation: int,
        result: str | None = None,
    ) -> bool:
        return self.configuration_write_tracker.mark(
            key, status, generation=generation, result=result
        )

    async def async_apply_options(self, data: dict[str, Any], *, section: str) -> None:
        """Apply one saved options section without changing entry ownership or storage."""
        if section == "general":
            self.location = data.get(CONF_LOCATION, "")
            self.external_meter.poll_interval = data[CONF_POLL_INTERVAL]
        elif section == "energy_sources":
            self.battery_power_entity = data.get(CONF_BATTERY_POWER_ENTITY) or None
            self.battery_power_sign = (
                data.get(CONF_BATTERY_POWER_SIGN, BATTERY_POSITIVE_DISCHARGE)
                if self.battery_power_entity
                else BATTERY_POSITIVE_DISCHARGE
            )
            self.site_accounting_options = dict(data)
        elif section == "site_accounting":
            self.site_accounting_options = dict(data)
        else:
            raise ValueError(f"Unknown options section: {section}")
        self.async_set_updated_data(True)
        if section == "site_accounting":
            guard = self.runtime_data.get(ENERGY_STOP_GUARD)
            if guard is not None:
                guard.refresh()

    def write_block_reason(self, control: ChargingControl) -> str | None:
        """Apply the shared control policy to this charger's current observations."""
        return control_write_block_reason(
            control,
            self.configuration_values,
            connected=self.connected,
            transaction_active=self.transaction_is_active,
            charger_faulted=self.charger_is_faulted,
        )

    def schedule_configuration_refresh(
        self, *, delay: float = CONFIGURATION_WRITE_SPACING_SECONDS
    ) -> asyncio.Task[bool]:
        return self.configuration_readback.schedule(delay=delay)

    def schedule_auto_charge_schedule_write(
        self,
        write_callback: Callable[[], Awaitable[None]],
        *,
        delay: float = 0.5,
    ) -> asyncio.Task[None]:
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
                _LOGGER.exception("Failed to queue debounced Auto Charge schedule")
            finally:
                if self._auto_charge_schedule_task is asyncio.current_task():
                    self._auto_charge_schedule_task = None

        task: asyncio.Task[None] = self.hass.async_create_task(_delayed_write())
        self._auto_charge_schedule_task = task
        return task

    def update_pv_linkage_draft(self, **changes: object) -> None:
        self.pv_draft.update(changes, self.configuration_values)
        self.async_set_updated_data(True)

    def record_pv_linkage_apply_result(
        self,
        result: PvLinkageApplyResult,
    ) -> None:
        """Expose the latest logical compound-write outcome."""
        self.pv_draft.apply_result = result
        self.async_set_updated_data(True)

    def mark_pv_linkage_draft_applied(self, expected_draft: PvLinkageDraft) -> bool:
        if not self.pv_draft.mark_applied(expected_draft):
            return False
        self.async_set_updated_data(True)
        return True

    def mark_connection_activity(self, action: str) -> None:
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

    def pause_polling_until(self, until: float) -> None:
        """Pause this entry's external meter poll until a monotonic time."""
        current = self.runtime_data.get(SKIP_POLLING_UNTIL, 0)
        self.runtime_data[SKIP_POLLING_UNTIL] = max(current, until)

    def set_disconnected(self) -> None:
        """Mark the active OCPP transport connection as disconnected."""
        was_connected = self.connected
        self.connected = False
        self._connection_changed.clear()
        if was_connected:
            _LOGGER.info("Charge point disconnected: %s", self.charge_point_id)
        if self.ingest.reset_live_power():
            _LOGGER.debug("Live power reset after disconnect")
        self.async_set_updated_data(True)

    async def async_shutdown(self) -> None:
        """Cancel coordinator-owned background work during integration unload."""
        self._shutting_down = True
        self.write_queue.begin_shutdown()
        tasks = (
            self.configuration_readback.task,
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

    # Inbound OCPP observations (see runtime/ocpp_ingest.py)

    def set_status(self, status: object) -> None:
        self.ingest.set_status(status)

    def record_boot_notification(self, payload: dict[str, Any]) -> None:
        self.ingest.record_boot_notification(payload)

    def record_status_notification(
        self, connector_id: int, status: str, error_code: str | None = None, **payload: Any
    ) -> None:
        self.ingest.record_status_notification(connector_id, status, error_code, **payload)

    def process_fault_message(self, vendor_id: object, data: str) -> None:
        self.ingest.process_fault_message(vendor_id, data)

    def process_meter_values(
        self,
        meter_values: list[dict[str, Any]],
        *,
        connector_id: int | None = None,
        transaction_id: int | str | None = None,
    ) -> None:
        self.ingest.process_meter_values(
            meter_values, connector_id=connector_id, transaction_id=transaction_id
        )

    def effective_meter_gap_seconds(self) -> float:
        return self.ingest.effective_meter_gap_seconds()

    def process_configuration(
        self, configuration: Sequence[object], unknown_keys: Iterable[object] = ()
    ) -> None:
        self.ingest.process_configuration(configuration, unknown_keys)

    def record_external_meter_poll_timeout(self) -> None:
        self.ingest.record_external_meter_poll_timeout()

    def reset_external_meter_poll_timeouts(self) -> None:
        self.ingest.reset_external_meter_poll_timeouts()

    def process_external_meter(self, data_str: str) -> bool:
        return self.ingest.process_external_meter(data_str)

    @property
    def charger_is_faulted(self) -> bool:
        """Return whether the current OCPP charger status is Faulted."""
        return normalize_ocpp_status(self.status) == "faulted"

    def schedule_fault_storage_save(self) -> None:
        """Coalesce paired StatusNotification/faultmessage storage writes."""
        self._store.async_delay_save(self._storage_data, 1)

    def start_transaction(
        self,
        transaction_id: int,
        id_tag: str | None = None,
        *,
        connector_id: int | None = None,
        meter_start: float | None = None,
        **payload: Any,
    ) -> None:
        """Delegate this transition to the session lifecycle."""
        return self.sessions.start_transaction(
            transaction_id,
            id_tag,
            connector_id=connector_id,
            meter_start=meter_start,
            **payload,
        )

    def stop_transaction(
        self,
        reason: str | None = None,
        *,
        transaction_id: int | str | None = None,
        meter_stop: float | None = None,
        **payload: Any,
    ) -> None:
        """Delegate this transition to the session lifecycle."""
        return self.sessions.stop_transaction(
            reason, transaction_id=transaction_id, meter_stop=meter_stop, **payload
        )

    def record_stop_requested(self, *, reason: str = "remote_stop") -> None:
        """Delegate this transition to the session lifecycle."""
        return self.sessions.record_stop_requested(reason=reason)

    # Growatt session records

    def process_session_record(self, record: GrowattSessionRecord) -> None:
        """Delegate this transition to the session lifecycle."""
        return self.sessions.process_session_record(record)
