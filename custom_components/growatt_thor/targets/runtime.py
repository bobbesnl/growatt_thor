"""Capture-backed native charging targets, reservations and daily schedules."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

from ..const import DOMAIN
from ..runtime.keys import ACTIVE_CHARGE_POINT, SKIP_POLLING_UNTIL, TARGET_HANDLERS, TARGET_RUNTIME
from ..runtime.write_results import ChargerCommandStatus
from ..timestamps import installation_time_zone
from .charger_ops import TargetChargerOperations
from .model import (
    ChargingTarget,
    TargetState,
    target_plan,
)
from .requests import (
    InvalidReservationExpiry,
    TargetRecord,
    new_scheduled_request,
    new_target_request,
)
from .runner import run_reservation_sequence, run_target_sequence
from .schedule import (
    iso_utc,
    next_daily_start,
    parse_start_at,
    stored_start_at,
    utc_now,
)
from .wire import send_target

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant, ServiceCall

    from ..coordinator import GrowattCoordinator
    from ..ocpp.server import GrowattChargePoint

# Persisted HA records remain dictionaries; ChargingTarget validates domain values.

_LOGGER = logging.getLogger(__name__)
SERVICES = (
    "preview_charging_target",
    "start_charging_target",
    "acknowledge_target_reset",
    "prepare_rfid_charging_target",
    "charging_target_status",
    "prepare_plug_charging_target",
    "schedule_charging_target",
    "cancel_scheduled_charging_target",
)

_SAFE_REPLACEMENT_STATES = {
    TargetState.BLOCKED_BEFORE_TARGET,
    TargetState.COMPLETED,
    TargetState.SCHEDULED_CANCELLED,
    TargetState.SCHEDULED_MISSED,
    TargetState.TARGET_REJECTED,
}
_WAITING_STATES = {
    TargetState.TARGET_ACCEPTED_WAITING_FOR_PLUG,
    TargetState.TARGET_ACCEPTED_WAITING_FOR_RFID,
}
_DAILY_REPEATABLE_RESULTS = {
    TargetState.BLOCKED_BEFORE_TARGET,
    TargetState.START_ACCEPTED,
    TargetState.TARGET_REJECTED,
}
_TARGET_START_PAUSE_SECONDS = 1
_TARGET_RESERVATION_PAUSE_SECONDS = 1
_REQUEST_EXPIRY_SECONDS = 90


class ChargingTargetRuntime:
    """Own one entry's persisted request, execution lock and schedule timer."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: GrowattCoordinator,
        *,
        now_utc: Callable[[], datetime] = utc_now,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.charger = TargetChargerOperations(coordinator)
        self._now_utc = now_utc
        self._store = Store(hass, 1, f"{DOMAIN}.charging_target.{entry.entry_id}")
        # The lock serializes request changes; busy also covers time spent waiting
        # in the shared write queue, after the service handler has released the lock.
        self._lock = asyncio.Lock()
        self._busy = False
        self._scheduled_handle: asyncio.TimerHandle | None = None

    async def async_setup(self) -> None:
        retained = await self._store.async_load()
        self.coordinator.charging_target_request = retained if isinstance(retained, dict) else None
        self.coordinator.charging_target_pilot_enabled = True
        if (
            isinstance(retained, dict)
            and retained.get("recurrence") == "daily"
            and not retained.get("local_time")
        ):
            start_at = stored_start_at(retained.get("scheduled_for"))
            if start_at is not None:
                retained = {
                    **retained,
                    "local_time": start_at.astimezone(ZoneInfo(retained["time_zone"])).strftime(
                        "%H:%M:%S"
                    ),
                }
                await self.persist(retained)

        self.coordinator.runtime_data[TARGET_HANDLERS] = {
            SERVICES[0]: self.preview,
            SERVICES[1]: self.start,
            SERVICES[2]: self.acknowledge,
            SERVICES[3]: self.prepare_rfid,
            SERVICES[4]: self.status,
            SERVICES[5]: self.prepare_plug,
            SERVICES[6]: self.schedule,
            SERVICES[7]: self.cancel_scheduled,
        }
        self.coordinator.transaction_hooks = self

        if isinstance(retained, dict) and retained.get("state") == TargetState.SCHEDULED:
            start_at = stored_start_at(retained.get("scheduled_for"))
            if start_at is not None and start_at > self._now_utc():
                self.arm_schedule(retained)
            elif retained.get("recurrence") == "daily" and start_at is not None:
                await self.advance_daily(retained, TargetState.MISSED_WHILE_UNAVAILABLE)
            else:
                await self.persist(
                    {
                        **retained,
                        "state": TargetState.SCHEDULED_MISSED,
                        "updated_at": self.coordinator.now(),
                    }
                )
        elif isinstance(retained, dict) and retained.get("state") in {
            TargetState.QUEUED,
            TargetState.RESERVATION_QUEUED,
            TargetState.SENDING_RESERVATION,
            TargetState.SENDING_TARGET,
            TargetState.TARGET_ACCEPTED,
            TargetState.SENDING_START,
            TargetState.CANCELLATION_QUEUED,
            TargetState.SENDING_CANCELLATION,
        }:
            # HA may have stopped after sending but before saving the reply.
            # Replaying a native target could change the charger twice; retain doubt.
            await self.persist(
                {
                    **retained,
                    "state": TargetState.OUTCOME_UNKNOWN,
                    "updated_at": self.coordinator.now(),
                }
            )

    async def enqueue(self, operation, request_id: str) -> None:
        """Release busy and reconcile requests the shared queue never executes."""
        started = False

        async def execute():
            nonlocal started
            started = True
            await operation()

        async def reconcile(result):
            async with self._lock:
                request = self.coordinator.charging_target_request
                if not isinstance(request, dict) or request.get("request_id") != request_id:
                    return
                self._busy = False
                # An unsent cancellation leaves a native reservation in place.
                # Preserve that doubt rather than claiming it was cancelled.
                state = TargetState.OUTCOME_UNKNOWN
                if request.get("state") != TargetState.CANCELLATION_QUEUED and result.status in {
                    ChargerCommandStatus.SKIPPED,
                    ChargerCommandStatus.EXPIRED,
                }:
                    state = TargetState.BLOCKED_BEFORE_TARGET
                await self.persist(
                    {**request, "state": state, "updated_at": self.coordinator.now()}
                )

        def completed(result):
            if not started:
                self.hass.async_create_task(reconcile(result))

        handle = await self.coordinator.queue_write(execute)
        if handle is not None:
            handle.add_done_callback(completed)

    async def persist(self, record: TargetRecord | None) -> None:
        await self._store.async_save(record)
        self.coordinator.charging_target_request = record
        self.coordinator.async_set_updated_data(True)

    def cancel_timer(self) -> None:
        if self._scheduled_handle is not None:
            self._scheduled_handle.cancel()
            self._scheduled_handle = None

    def parse(self, data: Mapping[str, Any]) -> ChargingTarget:
        try:
            return ChargingTarget.parse(data["kind"], data["value"])
        except ValueError as exc:
            raise HomeAssistantError(str(exc)) from None

    def replacing_request(
        self,
        previous: TargetRecord | None,
        replace_id: str | None,
        target: ChargingTarget,
    ) -> bool:
        if previous is None:
            if replace_id:
                raise HomeAssistantError("target_refresh_conflict")
            return False
        if replace_id != previous.get("request_id"):
            raise HomeAssistantError("previous_native_target_requires_manual_reconciliation")
        if previous.get("state") in _SAFE_REPLACEMENT_STATES:
            return True
        if previous.get("state") in _WAITING_STATES:
            try:
                same_target = (
                    ChargingTarget.parse(previous.get("kind"), previous.get("value")) == target
                )
            except ValueError:
                same_target = False
            if same_target:
                return True
        raise HomeAssistantError("target_refresh_conflict")

    def operation_check(
        self,
        cp: GrowattChargePoint | None,
        activation: str,
        issued: float,
        connection_started_at: str | None,
    ) -> str | None:
        if time.monotonic() - issued > _REQUEST_EXPIRY_SECONDS:
            return "request_expired"
        if self.coordinator.connection_started_at != connection_started_at:
            return "connection_changed"
        return self.charger.block_reason(cp, activation)

    def pause_polling(self, seconds: float = _REQUEST_EXPIRY_SECONDS) -> None:
        pause_until = (
            self.hass.loop.time() + seconds + self.coordinator.write_queue.poll_pause_after_write
        )
        self.coordinator.runtime_data[SKIP_POLLING_UNTIL] = max(
            self.coordinator.runtime_data.get(SKIP_POLLING_UNTIL, 0), pause_until
        )

    async def preview(self, service: ServiceCall) -> dict[str, Any]:
        return target_plan(self.parse(service.data), service.data.get("start", "now"))

    async def start(self, service: ServiceCall, *, activation: str = "remote") -> TargetRecord:
        if service.data.get("entry_id") not in {None, self.entry.entry_id}:
            raise HomeAssistantError("wrong_charger_entry")
        target = self.parse(service.data)
        async with self._lock:
            previous = self.coordinator.charging_target_request
            replacing = self.replacing_request(
                previous, service.data.get("replace_request_id"), target
            )
            if self._busy:
                raise HomeAssistantError("target_request_or_transaction_busy")
            cp = self.coordinator.runtime_data.get(ACTIVE_CHARGE_POINT)
            if reason := self.charger.block_reason(cp, activation):
                raise HomeAssistantError(reason)
            request = new_target_request(
                target,
                activation=activation,
                now=self.coordinator.now,
                connection_started_at=self.coordinator.connection_started_at,
                previous=previous,
                replacing=replacing,
            )
            await self.persist(request)
            self._busy = True
            issued = time.monotonic()
            connection_started_at = self.coordinator.connection_started_at

        async def save(state: str) -> None:
            nonlocal request
            request = {**request, "state": state, "updated_at": self.coordinator.now()}
            await self.persist(request)
            _LOGGER.info("Charging target %s: %s", request["request_id"], state)

        def check() -> str | None:
            return self.operation_check(cp, activation, issued, connection_started_at)

        async def execute() -> None:
            try:
                self.pause_polling()
                await run_target_sequence(
                    target,
                    check=check,
                    save=save,
                    send_target=lambda value: send_target(cp, value),
                    start=None
                    if activation in {"plug", "rfid"}
                    else lambda: self.charger.remote_start(cp),
                    pause_seconds=_TARGET_START_PAUSE_SECONDS,
                    waiting_state=(
                        TargetState.TARGET_ACCEPTED_WAITING_FOR_PLUG
                        if activation == "plug"
                        else TargetState.TARGET_ACCEPTED_WAITING_FOR_RFID
                    ),
                )
                # A fast charger can emit StartTransaction before the
                # RemoteStart call unwinds and its callback observes the new
                # request state. Reconcile that race from coordinator truth.
                if (
                    request.get("state") == TargetState.START_ACCEPTED
                    and self.coordinator.transaction_is_active
                ):
                    await save(TargetState.ACTIVE)
            finally:
                self._busy = False

        try:
            await self.enqueue(execute, request["request_id"])
        except Exception:  # noqa: BLE001 - persist sanitized outcome only
            self._busy = False
            await save(TargetState.QUEUE_FAILED)
            raise HomeAssistantError("target_queue_failed") from None
        return dict(request)

    async def prepare_rfid(self, service: ServiceCall) -> TargetRecord:
        return await self.start(service, activation="rfid")

    async def prepare_plug(self, service: ServiceCall) -> TargetRecord:
        return await self.start(service, activation="plug")

    def arm_schedule(self, request: TargetRecord) -> bool:
        start_at = stored_start_at(request.get("scheduled_for"))
        current = self._now_utc()
        request_id = request.get("request_id")
        if (
            request.get("state") != TargetState.SCHEDULED
            or start_at is None
            or start_at <= current
            or not isinstance(request_id, str)
            or not request_id
        ):
            return False
        self.cancel_timer()
        self._scheduled_handle = self.hass.loop.call_later(
            (start_at - current).total_seconds(),
            lambda: self.hass.async_create_task(self.execute_scheduled(request_id)),
        )
        return True

    async def advance_daily(self, request: TargetRecord, result: str) -> None:
        start_at = stored_start_at(request.get("scheduled_for"))
        if start_at is None:
            await self.persist({**request, "state": TargetState.SCHEDULED_MISSED})
            return
        next_at = next_daily_start(
            start_at,
            now=self._now_utc(),
            time_zone=request["time_zone"],
            local_time=request.get("local_time"),
        )
        updated = {
            **request,
            "state": TargetState.SCHEDULED,
            "scheduled_for": iso_utc(next_at),
            "last_run_at": iso_utc(self._now_utc()),
            "last_run_state": result,
            "updated_at": self.coordinator.now(),
        }
        await self.persist(updated)
        self.arm_schedule(updated)

    async def execute_scheduled(self, request_id: str) -> None:
        self._scheduled_handle = None
        async with self._lock:
            request = self.coordinator.charging_target_request
            if (
                self._busy
                or not isinstance(request, dict)
                or request.get("request_id") != request_id
                or request.get("state") != TargetState.SCHEDULED
            ):
                return
            self._busy = True

        target = ChargingTarget.parse(request["kind"], request["value"])
        recurrence = request.get("recurrence", "once")
        activation = "daily_start" if recurrence == "daily" else "reserved_start"
        cp = self.coordinator.runtime_data.get(ACTIVE_CHARGE_POINT)
        issued = time.monotonic()
        connection_started_at = self.coordinator.connection_started_at

        async def save(state: str) -> None:
            nonlocal request
            request = {
                **request,
                "state": state,
                "updated_at": self.coordinator.now(),
                "connection_started_at": self.coordinator.connection_started_at,
            }
            await self.persist(request)
            _LOGGER.info("Scheduled charging target %s: %s", request_id, state)

        def check() -> str | None:
            return self.operation_check(cp, activation, issued, connection_started_at)

        async def execute() -> None:
            try:
                self.pause_polling()
                await run_target_sequence(
                    target,
                    check=check,
                    save=save,
                    send_target=lambda value: send_target(cp, value),
                    start=lambda: self.charger.remote_start(cp),
                    # Growatt sends both calls at the reservation boundary. We
                    # wait only for target acceptance, then start immediately.
                    pause_seconds=0,
                )
                result = request.get("state", TargetState.OUTCOME_UNKNOWN)
                if recurrence == "daily" and result in _DAILY_REPEATABLE_RESULTS:
                    if (
                        result == TargetState.START_ACCEPTED
                        and self.coordinator.transaction_is_active
                    ):
                        result = TargetState.CHARGING
                    await self.advance_daily(request, result)
                elif (
                    recurrence != "daily"
                    and result == TargetState.START_ACCEPTED
                    and self.coordinator.transaction_is_active
                ):
                    await save(TargetState.ACTIVE)
            finally:
                self._busy = False

        try:
            await self.enqueue(execute, request["request_id"])
        except Exception:  # noqa: BLE001 - retained state explains uncertainty
            self._busy = False
            await save(TargetState.QUEUE_FAILED)

    async def schedule(self, service: ServiceCall) -> None:
        if service.data["entry_id"] != self.entry.entry_id:
            raise HomeAssistantError("wrong_charger_entry")
        target = self.parse(service.data)
        recurrence = service.data.get("recurrence", "once")
        try:
            start_at = parse_start_at(service.data["start_at"], now=self._now_utc())
        except ValueError as exc:
            raise HomeAssistantError(str(exc)) from None
        time_zone = str(installation_time_zone(self.hass, preserve_empty=True))

        async with self._lock:
            previous = self.coordinator.charging_target_request
            replacing = self.replacing_request(
                previous, service.data.get("replace_request_id"), target
            )
            if self._busy:
                raise HomeAssistantError("target_request_or_transaction_busy")
            cp = self.coordinator.runtime_data.get(ACTIVE_CHARGE_POINT)
            activation = "reserve" if recurrence == "once" else "remote"
            if reason := self.charger.block_reason(cp, activation):
                raise HomeAssistantError(reason)
            try:
                request = new_scheduled_request(
                    target,
                    start_at=start_at,
                    time_zone=time_zone,
                    recurrence=recurrence,
                    now=self.coordinator.now,
                    previous=previous,
                    replacing=replacing,
                )
            except InvalidReservationExpiry as exc:
                raise HomeAssistantError(str(exc)) from None
            self.cancel_timer()
            await self.persist(request)
            if recurrence == "daily":
                self.arm_schedule(request)
                return
            self._busy = True
            issued = time.monotonic()
            connection_started_at = self.coordinator.connection_started_at

        async def save(state: str) -> None:
            nonlocal request
            request = {**request, "state": state, "updated_at": self.coordinator.now()}
            await self.persist(request)
            _LOGGER.info("Charging reservation %s: %s", request["request_id"], state)

        def check() -> str | None:
            return self.operation_check(cp, "reserve", issued, connection_started_at)

        async def execute() -> None:
            try:
                self.pause_polling()
                await run_reservation_sequence(
                    target,
                    check=check,
                    save=save,
                    send_target=lambda value: send_target(cp, value),
                    reserve=lambda: self.charger.reserve(cp, request),
                    pause_seconds=_TARGET_RESERVATION_PAUSE_SECONDS,
                )
                if request.get("state") == TargetState.SCHEDULED and not self.arm_schedule(request):
                    await save(TargetState.SCHEDULED_MISSED)
            finally:
                self._busy = False

        try:
            await self.enqueue(execute, request["request_id"])
        except Exception:  # noqa: BLE001 - persist sanitized outcome only
            self._busy = False
            await save(TargetState.QUEUE_FAILED)
            raise HomeAssistantError("target_queue_failed") from None

    async def cancel_scheduled(self, service: ServiceCall) -> None:
        async with self._lock:
            request = self.coordinator.charging_target_request
            if (
                self._busy
                or not isinstance(request, dict)
                or request.get("request_id") != service.data["request_id"]
                or request.get("state") != TargetState.SCHEDULED
            ):
                raise HomeAssistantError("scheduled_target_not_cancellable")
            self.cancel_timer()
            if request.get("recurrence") == "daily":
                await self.persist(
                    {
                        **request,
                        "state": TargetState.SCHEDULED_CANCELLED,
                        "updated_at": self.coordinator.now(),
                    }
                )
                return
            reservation_id = request.get("reservation_id")
            cp = self.coordinator.runtime_data.get(ACTIVE_CHARGE_POINT)
            if (
                not isinstance(reservation_id, int)
                or not self.coordinator.connected
                or cp is None
                or self.coordinator.runtime_data.get(ACTIVE_CHARGE_POINT) is not cp
            ):
                raise HomeAssistantError("reservation_cancel_unavailable")
            request = {
                **request,
                "state": TargetState.CANCELLATION_QUEUED,
                "updated_at": self.coordinator.now(),
            }
            await self.persist(request)
            self._busy = True

        async def execute_cancel() -> None:
            nonlocal request
            try:
                request = {
                    **request,
                    "state": TargetState.SENDING_CANCELLATION,
                    "updated_at": self.coordinator.now(),
                }
                await self.persist(request)
                status = await self.charger.cancel_reservation(cp, reservation_id)
                request = {
                    **request,
                    "state": (
                        TargetState.SCHEDULED_CANCELLED
                        if status == "Accepted"
                        else TargetState.CANCELLATION_REJECTED_RESERVATION_MAY_REMAIN
                    ),
                    "updated_at": self.coordinator.now(),
                }
                await self.persist(request)
            except Exception:  # noqa: BLE001 - never leak OCPP payloads
                request = {
                    **request,
                    "state": TargetState.OUTCOME_UNKNOWN,
                    "updated_at": self.coordinator.now(),
                }
                await self.persist(request)
            finally:
                self._busy = False

        try:
            await self.enqueue(execute_cancel, request["request_id"])
        except Exception:  # noqa: BLE001
            self._busy = False
            await self.persist({**request, "state": TargetState.QUEUE_FAILED})
            raise HomeAssistantError("target_queue_failed") from None

    async def status(self, service: ServiceCall) -> dict[str, TargetRecord | None]:
        return {"request": self.coordinator.charging_target_request}

    async def acknowledge(self, service: ServiceCall) -> None:
        async with self._lock:
            if self._busy or self.coordinator.transaction_is_active:
                raise HomeAssistantError("target_request_or_transaction_busy")
            request = self.coordinator.charging_target_request
            if isinstance(request, dict) and request.get("state") in {
                TargetState.RESERVATION_QUEUED,
                TargetState.SCHEDULED,
                TargetState.CANCELLATION_QUEUED,
                TargetState.SENDING_CANCELLATION,
            }:
                raise HomeAssistantError("scheduled_target_requires_cancel")
            self.cancel_timer()
            await self.persist(None)

    async def transaction_started(self, *_args: object, **_kwargs: object) -> None:
        async with self._lock:
            request = self.coordinator.charging_target_request
            if not isinstance(request, dict):
                return
            if request.get("recurrence") == "daily":
                if request.get("last_run_state") != TargetState.START_ACCEPTED:
                    return
                await self.persist(
                    {
                        **request,
                        "last_run_state": TargetState.CHARGING,
                        "updated_at": self.coordinator.now(),
                    }
                )
                return
            if request.get("state") in {TargetState.START_ACCEPTED, *_WAITING_STATES}:
                await self.persist(
                    {**request, "state": TargetState.ACTIVE, "updated_at": self.coordinator.now()}
                )

    async def transaction_stopped(self, *_args: object, **_kwargs: object) -> None:
        async with self._lock:
            request = self.coordinator.charging_target_request
            if not isinstance(request, dict):
                return
            if request.get("recurrence") == "daily":
                if request.get("last_run_state") != TargetState.CHARGING:
                    return
                await self.persist(
                    {
                        **request,
                        "last_run_state": TargetState.COMPLETED,
                        "updated_at": self.coordinator.now(),
                    }
                )
                return
            if request.get("state") == TargetState.ACTIVE:
                await self.persist(
                    {
                        **request,
                        "state": TargetState.COMPLETED,
                        "updated_at": self.coordinator.now(),
                    }
                )

    def close(self) -> None:
        """Release this entry's timer and transaction callbacks on unload."""
        self.cancel_timer()
        self.coordinator.transaction_hooks = None


async def async_setup_target_runtime(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: GrowattCoordinator,
    *,
    now_utc: Callable[[], datetime] = utc_now,
) -> None:
    """Attach one controller without changing the public HA service contract."""
    runtime = ChargingTargetRuntime(hass, entry, coordinator, now_utc=now_utc)
    await runtime.async_setup()
    coordinator.runtime_data[TARGET_RUNTIME] = runtime


def async_unload_target_runtime(hass: HomeAssistant, entry) -> None:
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    runtime = entry_data.pop(TARGET_RUNTIME, None)
    if runtime is not None:
        runtime.close()
    entry_data.pop(TARGET_HANDLERS, None)
