import logging
import re
from datetime import datetime, timezone
from collections import deque
import asyncio

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.storage import Store

from .charging_sessions import CORRELATION_MATCHED, build_unified_session
from .configuration import (
    ConfigurationValue,
    merge_configuration_values,
    normalize_unknown_configuration_keys,
)
from .const import DOMAIN
from .external_meter import parse_external_meter_data
from .meter_samples import parse_meter_values
from .ocpp_diagnostics import create_ocpp_snapshot
from .session_records import GrowattSessionRecord
from .session_state import LastSessionState
from .transaction_ids import TransactionIdAllocator

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "growatt_thor_statistics"
STORAGE_VERSION = 1


class GrowattCoordinator(DataUpdateCoordinator):
    """Coordinator for Growatt THOR OCPP data."""

    def __init__(self, hass, source_instance_id=None):
        super().__init__(hass, _LOGGER, name="Growatt THOR Coordinator")

        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.source_instance_id = source_instance_id
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
        self.id_tag = None

        # Latest normalized OCPP requests retained for HA diagnostics.
        self.boot_notification = None
        self.last_status_notification = None
        self.last_meter_values = None
        self.active_transaction = None
        self.last_completed_transaction = None
        self.last_current_record = None
        self.last_frozen_record = None

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

        # ── Last session ─────────────────
        self.last_session_energy = None           # kWh
        self.last_session_cost = None             # float
        self.last_session_start = None            # str
        self.last_session_end = None              # str
        self.last_session_plug_time = None        # str
        self.last_session_unplug_time = None      # str
        self.last_session_duration_minutes = None # float
        self.last_session_id = None               # str
        self.last_session_source = None           # str
        self.last_session_transaction_id = None   # str
        self.last_session_charge_mode = None      # str
        self.last_session_work_mode = None        # str
        self._last_session_record_key = None

        # ── Cumulatief totaal (persistent) ─
        self.total_energy_charged = 0.0           # kWh

        # ── External meter (grid connection) ───
        self.grid_power = None
        self.grid_voltages = {}
        self.grid_currents = {}
        self.external_meter_used = None
        self.external_meter_wring = None
        self.external_meter_last_updated_at = None

        # WRITE QUEUE SYSTEEM
        self._write_queue = deque()
        self._write_lock = asyncio.Lock()
        self._write_task = None

        # Rate limiting / polling pause (monotonic time)
        self._last_write_monotonic = None
        self._min_write_interval = 20.0
        self._poll_pause_after_write = 20.0

    # ─────────────────────────────
    # PERSISTENT STORAGE
    # ─────────────────────────────

    async def async_load_storage(self):
        """Load persistent statistics from HA storage."""
        data = await self._store.async_load()
        if data:
            self.total_energy_charged = float(data.get("total_energy_charged", 0.0))
            self._transaction_id_allocator.restore(
                data.get("next_transaction_id", 1)
            )
            self._restore_last_session_state(
                LastSessionState.from_dict(data.get("last_session"))
            )
            _LOGGER.info(
                "📦 Loaded from storage: total_energy_charged=%.3f kWh, "
                "next_transaction_id=%d, last_session_transaction_id=%s",
                self.total_energy_charged,
                self._transaction_id_allocator.next_transaction_id,
                self.last_session_transaction_id,
            )
        else:
            _LOGGER.info("📦 No persistent storage found, starting fresh")

    async def async_save_storage(self):
        """Save persistent statistics to HA storage."""
        await self._store.async_save(
            {
                "total_energy_charged": self.total_energy_charged,
                "next_transaction_id": (
                    self._transaction_id_allocator.next_transaction_id
                ),
                "last_session": self._last_session_state().as_dict(),
            }
        )
        _LOGGER.debug(
            "💾 Saved to storage: total_energy_charged=%.3f kWh, "
            "next_transaction_id=%d",
            self.total_energy_charged,
            self._transaction_id_allocator.next_transaction_id,
        )

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
        self.last_session_id = state.session_id
        self.last_session_source = state.session_source
        self.last_session_transaction_id = state.transaction_id
        self.last_session_charge_mode = state.charge_mode
        self.last_session_work_mode = state.work_mode
        self._last_session_record_key = state.record_key

    # ─────────────────────────────
    # WRITE QUEUE METHODS
    # ─────────────────────────────

    async def queue_write(self, write_func, *args, dedupe_key=None, **kwargs):
        """Voeg een schrijfactie toe aan de queue."""
        write_item = {
            "func": write_func,
            "args": args,
            "kwargs": kwargs,
            "enqueued_at": datetime.now(),
            "dedupe_key": dedupe_key,
        }

        if dedupe_key is not None:
            self._write_queue = deque(
                item for item in self._write_queue if item.get("dedupe_key") != dedupe_key
            )

        self._write_queue.append(write_item)
        _LOGGER.debug("📥 Write queued. Queue size: %d", len(self._write_queue))

        if self._write_task is None or self._write_task.done():
            self._write_task = self.hass.async_create_task(self._process_write_queue())

    async def _process_write_queue(self):
        """Verwerk de write queue met rate limiting."""
        async with self._write_lock:
            try:
                while self._write_queue:
                    write_item = self._write_queue.popleft()

                    now_mono = self.hass.loop.time()

                    if self._last_write_monotonic is not None:
                        time_since_last = now_mono - self._last_write_monotonic
                        wait_time = max(0.0, self._min_write_interval - time_since_last)

                        if wait_time > 0:
                            _LOGGER.info(
                                "⏳ Waiting %.1fs before next write. Queue: %d remaining",
                                wait_time,
                                len(self._write_queue),
                            )
                            await asyncio.sleep(wait_time)

                    try:
                        _LOGGER.info(
                            "✍️ Executing write command. Remaining in queue: %d",
                            len(self._write_queue),
                        )

                        until = self.hass.loop.time() + self._poll_pause_after_write
                        current = self.hass.data[DOMAIN].get("skip_polling_until", 0)
                        self.hass.data[DOMAIN]["skip_polling_until"] = max(current, until)
                        _LOGGER.info("🛡️ Polling paused BEFORE write (Thor FW protection)")

                        result = await write_item["func"](*write_item["args"], **write_item["kwargs"])

                        self._last_write_monotonic = self.hass.loop.time()

                        _LOGGER.info("✅ Write completed successfully. Result: %s", result)

                    except Exception as err:
                        _LOGGER.error("❌ Write command failed: %s", err, exc_info=True)

            finally:
                self._write_task = None

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

    def set_charge_point(self, cp_id):
        """Set charge point ID and notify sensors."""
        self.charge_point_id = cp_id
        self.connected = True
        self.connection_started_at = self.now()
        self.last_message_at = self.connection_started_at
        self.last_message_action = "WebSocketConnect"
        self.last_heartbeat_at = None
        _LOGGER.info("Charge point connected: %s", cp_id)
        self.async_set_updated_data(True)

    def mark_connection_activity(self, action):
        """Record the latest inbound OCPP message."""
        timestamp = self.now()
        self.connected = True
        self.last_message_at = timestamp
        self.last_message_action = action
        if action == "Heartbeat":
            self.last_heartbeat_at = timestamp
        self.async_set_updated_data(True)

    def set_disconnected(self):
        """Mark the active OCPP transport connection as disconnected."""
        was_connected = self.connected
        self.connected = False
        if was_connected:
            _LOGGER.info("Charge point disconnected: %s", self.charge_point_id)
        self.async_set_updated_data(True)

    def set_status(self, status):
        """Set charger status and notify sensors."""
        value = status.value if hasattr(status, "value") else str(status)

        if self.status != value:
            self.status = value
            _LOGGER.debug("Status changed to: %s", value)

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
        self.last_status_notification = create_ocpp_snapshot(self.now(), request)
        self.set_status(status)

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
        self.transaction_id = transaction_id
        self.id_tag = id_tag
        self.status = "Charging"

        request = {
            "connector_id": connector_id,
            "id_tag": id_tag,
            "meter_start": meter_start,
            **payload,
        }
        start_snapshot = create_ocpp_snapshot(self.now(), request)
        start_snapshot["response"] = {"transaction_id": transaction_id}
        self.active_transaction = {"start": start_snapshot}

        _LOGGER.info("🔋 New transaction started → Resetting energy counter")
        self.energy = 0

        _LOGGER.info("Transaction started: %s", transaction_id)
        self.async_set_updated_data(True)

    def stop_transaction(
        self,
        reason=None,
        *,
        transaction_id=None,
        meter_stop=None,
        **payload,
    ):
        """Stop charging transaction."""
        stopped_transaction_id = (
            self.transaction_id if transaction_id is None else transaction_id
        )
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
        completed = dict(self.active_transaction or {})
        completed["stop"] = create_ocpp_snapshot(self.now(), request)
        self.last_completed_transaction = completed
        self.active_transaction = None

        _LOGGER.info("🛑 Transaction stopped → Resetting charge values")
        self.power = 0
        self.currents = {"L1": 0, "L2": 0, "L3": 0}
        self.voltages = {"L1": 0, "L2": 0, "L3": 0}
        self.phase_power = {"L1": 0, "L2": 0, "L3": 0}

        self.transaction_id = None
        self.status = "Idle"
        self.async_set_updated_data(True)

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
        parsed_values = parse_meter_values(meter_values)
        self.last_meter_values = {
            "received_at": self.now(),
            "connector_id": connector_id,
            "transaction_id": transaction_id,
            "meter_values": [entry.as_dict() for entry in parsed_values],
        }
        updated = False

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

        if self.phase_power:
            total = sum(self.phase_power.values())
            if self.power != total:
                self.power = total
                updated = True

        _LOGGER.debug(
            "Retained %d MeterValues entries%s",
            len(parsed_values),
            " and updated live sensors" if updated else "",
        )
        self.async_set_updated_data(True)

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

        for item in configuration:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            raw = item.get("value")

            try:
                if key == "G_MaxCurrent":
                    value = float(raw)
                    if self.max_current != value:
                        self.max_current = value
                        _LOGGER.debug("Config: MaxCurrent = %.1f A", value)
                        updated = True

                elif key == "G_ExternalLimitPower":
                    value = float(raw)
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
                    match = re.search(r'price1=(-?\d+\.\d+)', raw)
                    if match:
                        value = round(float(match.group(1)), 2)
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
        """Retain a Growatt session record and update session statistics."""
        snapshot = {"received_at": self.now(), "record": record}
        if record.message_id == "currentrecord":
            self.last_current_record = snapshot
        else:
            self.last_frozen_record = snapshot

        try:
            if record.parse_errors:
                _LOGGER.warning(
                    "Growatt %s contains invalid values: %s",
                    record.message_id,
                    "; ".join(record.parse_errors),
                )

            # The charger can send the same completed session as both message types.
            dedup_key = record.dedup_key
            if dedup_key is not None and self._last_session_record_key == dedup_key:
                _LOGGER.debug(
                    "Duplicate Growatt session record skipped (transaction=%s)",
                    record.transaction_id,
                )
                self.async_set_updated_data(True)
                return

            energy_kwh = record.energy_kwh
            cost = record.cost
            if energy_kwh is None or cost is None:
                _LOGGER.warning(
                    "Growatt %s retained but not applied because energy or cost is invalid",
                    record.message_id,
                )
                self.async_set_updated_data(True)
                return

            if dedup_key is not None:
                self._last_session_record_key = dedup_key

            start_str = record.start_time
            end_str = record.end_time
            duration_minutes = record.duration_minutes
            session = build_unified_session(
                self.last_completed_transaction,
                meter_values=self.last_meter_values,
                session_records=(snapshot,),
                charge_point_id=self.charge_point_id,
                source_instance_id=self.source_instance_id,
            )
            if (
                session is None
                or session["correlation"]["status"] != CORRELATION_MATCHED
            ):
                session = build_unified_session(
                    None,
                    session_records=(snapshot,),
                    charge_point_id=self.charge_point_id,
                    source_instance_id=self.source_instance_id,
                )
            identity = session["identity"]

            self.last_session_energy = energy_kwh
            self.last_session_cost = cost
            self.last_session_start = start_str
            self.last_session_end = end_str
            self.last_session_plug_time = record.plug_time
            self.last_session_unplug_time = record.unplug_time
            self.last_session_duration_minutes = duration_minutes
            self.last_session_id = identity["session_id"]
            self.last_session_source = identity["session_source"]
            self.last_session_transaction_id = record.transaction_id
            self.last_session_charge_mode = record.charge_mode
            self.last_session_work_mode = record.work_mode

            self.total_energy_charged += energy_kwh

            _LOGGER.info(
                "%s: energy=%.3f kWh, cost=%.2f, duration=%s min, total=%.3f kWh",
                record.message_id,
                energy_kwh,
                cost,
                f"{duration_minutes:.1f}" if duration_minutes is not None else "unknown",
                self.total_energy_charged,
            )

            # CSV logging via __init__.py helper
            append_fn = self.hass.data.get(DOMAIN, {}).get("append_session_to_csv")
            if append_fn:
                session_row = {
                    "timestamp": self.now(),
                    "charger_id": self.charge_point_id or "",
                    "location": self.location,
                    "start_time": start_str,
                    "end_time": end_str,
                    "energy_kwh": round(energy_kwh, 3),
                    "cost": round(cost, 2),
                    "duration_minutes": duration_minutes if duration_minutes is not None else "",
                    "transaction_id": record.transaction_id,
                }
                self.hass.async_create_task(append_fn(session_row))

            self.hass.async_create_task(self.async_save_storage())
            self.async_set_updated_data(True)

        except (ValueError, TypeError, KeyError) as exc:
            _LOGGER.warning(
                "Failed to process Growatt %s: %s",
                record.message_id,
                exc,
            )

    # ─────────────────────────────
    # Growatt external meter values
    # ─────────────────────────────

    def process_external_meter(self, data_str: str):
        """Process external meter values from get_external_meterval DataTransfer."""
        try:
            snapshot = parse_external_meter_data(data_str)

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

        except (ValueError, TypeError, KeyError) as exc:
            _LOGGER.warning("Failed to process external meter data '%s': %s", data_str, exc)
