"""Capture-backed native charging targets, reservations and daily schedules."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime
import logging
import secrets
import time
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from ocpp.v16 import call as ocpp_call

from ..charging.controls import selected_working_mode
from .runner import run_reservation_sequence, run_target_sequence
from .schedule import (
    iso_utc,
    next_daily_start,
    parse_start_at,
    reservation_expiry,
    stored_start_at,
    utc_now,
)
from .wire import send_target
from .model import (
    CAPTURE_FIRMWARE,
    NATIVE_STOP_VERIFIED,
    ChargingTarget,
    target_plan,
)
from ..configuration.values import configuration_entity_state
from ..const import DOMAIN
from ..ocpp.diagnostics import boot_notification_field

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant, ServiceCall
    from ..coordinator import GrowattCoordinator
    from ..ocpp.server import GrowattChargePoint

# Persisted HA records remain dictionaries; ChargingTarget validates domain values.
TargetRecord = dict[str, Any]

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
    "blocked_before_target",
    "completed",
    "scheduled_cancelled",
    "scheduled_missed",
    "target_rejected",
}
_WAITING_STATES = {
    "target_accepted_waiting_for_plug",
    "target_accepted_waiting_for_rfid",
}
_DAILY_REPEATABLE_RESULTS = {
    "blocked_before_target",
    "start_accepted",
    "target_rejected",
}
_TARGET_START_PAUSE_SECONDS = 1
_TARGET_RESERVATION_PAUSE_SECONDS = 1
_REQUEST_EXPIRY_SECONDS = 90


def _response_status(result: object) -> str | None:
    status = getattr(result, "status", None)
    status = getattr(status, "value", status)
    return status if isinstance(status, str) else None


def _request_history(previous: TargetRecord | None) -> list[TargetRecord]:
    if not previous:
        return []
    fields = (
        "request_id",
        "kind",
        "value",
        "state",
        "activation",
        "recurrence",
        "scheduled_for",
        "updated_at",
    )
    return [
        *previous.get("previous_requests", [])[-4:],
        {key: previous.get(key) for key in fields},
    ]


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
        self._now_utc = now_utc
        self._store = Store(hass, 1, f"{DOMAIN}.charging_target.{entry.entry_id}")
        # The lock serializes request changes; busy also covers time spent waiting
        # in the shared write queue, after the service handler has released the lock.
        self._lock = asyncio.Lock()
        self._busy = False
        self._scheduled_handle: asyncio.TimerHandle | None = None

    async def async_setup(self) -> None:
        retained = await self._store.async_load()
        self.coordinator.charging_target_request = (
            retained if isinstance(retained, dict) else None
        )
        self.coordinator.charging_target_pilot_enabled = True

        self.hass.data.setdefault(DOMAIN, {})["target_handlers"] = {
            SERVICES[0]: self.preview,
            SERVICES[1]: self.start,
            SERVICES[2]: self.acknowledge,
            SERVICES[3]: self.prepare_rfid,
            SERVICES[4]: self.status,
            SERVICES[5]: self.prepare_plug,
            SERVICES[6]: self.schedule,
            SERVICES[7]: self.cancel_scheduled,
        }
        self.coordinator._cancel_charging_target_schedule = self.cancel_timer
        self.coordinator._charging_target_transaction_started = self.transaction_started
        self.coordinator._charging_target_transaction_stopped = self.transaction_stopped

        if isinstance(retained, dict) and retained.get("state") == "scheduled":
            start_at = stored_start_at(retained.get("scheduled_for"))
            if start_at is not None and start_at > self._now_utc():
                self.arm_schedule(retained)
            elif retained.get("recurrence") == "daily" and start_at is not None:
                await self.advance_daily(retained, "missed_while_unavailable")
            else:
                await self.persist(
                    {**retained, "state": "scheduled_missed", "updated_at": self.coordinator.now()}
                )
        elif isinstance(retained, dict) and retained.get("state") in {
            "reservation_queued",
            "sending_reservation",
            "sending_target",
        }:
            # HA may have stopped after sending but before saving the reply.
            # Replaying a native target could change the charger twice; retain doubt.
            await self.persist(
                {**retained, "state": "outcome_unknown", "updated_at": self.coordinator.now()}
            )

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

    def charger_mode(self) -> str | None:
        return configuration_entity_state(
            "G_ChargerMode", self.coordinator.configuration_values.get("G_ChargerMode")
        )

    def remote_identifier_reason(self, cp: GrowattChargePoint) -> str | None:
        if not isinstance(cp.id, str) or not 1 <= len(cp.id) <= 20:
            return "remote_identifier_invalid"
        if (
            self.charger_mode() == "home_assistant_rfid"
            and not self.coordinator.authorization.policy.allows_ha_remote_start()
        ):
            return "remote_identifier_not_authorized"
        return None

    def block_reason(
        self, cp: GrowattChargePoint | None, activation: str
    ) -> str | None:
        if (
            not self.coordinator.connected
            or cp is None
            or self.hass.data.get(DOMAIN, {}).get("charge_point") is not cp
        ):
            return "charger_disconnected_or_replaced"
        if self.coordinator.transaction_is_active:
            return "transaction_already_active"
        if self.coordinator.charger_is_faulted:
            return "charger_not_ready"
        if (
            boot_notification_field(self.coordinator.boot_notification, "firmware_version")
            != CAPTURE_FIRMWARE
        ):
            return "firmware_not_validated_for_pilot"
        if selected_working_mode(self.coordinator.configuration_values) != "fast":
            return "fast_mode_required"

        mode = self.charger_mode()
        status = self.coordinator.status
        if activation == "plug":
            if mode != "plug_and_charge":
                return "plug_and_charge_mode_required"
            return None if status == "Available" else "unplug_vehicle_before_setting_target"
        if activation == "rfid":
            if mode != "rfid_only":
                return "rfid_authorization_mode_required"
            return None if status in {"Available", "Preparing"} else "charger_not_ready"
        if activation == "reserve":
            if mode not in {"plug_and_charge", "home_assistant_rfid"}:
                return "remote_start_authorization_mode_required"
            # The target write precedes ReserveNow. Requiring an unplugged,
            # Available connector prevents Plug & Charge from starting early.
            if status != "Available":
                return "unplug_vehicle_before_setting_reservation"
            return self.remote_identifier_reason(cp)
        if activation == "reserved_start":
            if mode not in {"plug_and_charge", "home_assistant_rfid"}:
                return "remote_start_authorization_mode_required"
            # Growatt expires the captured reservation at the selected start
            # boundary. Depending on notification timing the connector can
            # already be Available or Preparing when this callback runs.
            if status not in {"Reserved", "Available", "Preparing"}:
                return "charger_reservation_not_active"
            return self.remote_identifier_reason(cp)
        if activation == "daily_start":
            if mode not in {"plug_and_charge", "home_assistant_rfid"}:
                return "remote_start_authorization_mode_required"
            if mode == "plug_and_charge" and status != "Preparing":
                return "vehicle_must_be_connected_at_daily_start"
            if status not in {"Available", "Preparing"}:
                return "charger_not_ready"
            return self.remote_identifier_reason(cp)
        if mode not in {"plug_and_charge", "home_assistant_rfid"}:
            return "remote_start_authorization_mode_required"
        if status not in {"Available", "Preparing"}:
            return "charger_not_ready"
        return self.remote_identifier_reason(cp)

    def replacing_request(
        self, previous: TargetRecord | None, replace_id: str | None, target: ChargingTarget
    ) -> bool:
        if previous is None:
            if replace_id:
                raise HomeAssistantError("target_refresh_conflict")
            return False
        if replace_id != previous.get("request_id"):
            raise HomeAssistantError(
                "previous_native_target_requires_manual_reconciliation"
            )
        if previous.get("state") in _SAFE_REPLACEMENT_STATES:
            return True
        if previous.get("state") in _WAITING_STATES:
            try:
                same_target = ChargingTarget.parse(
                    previous.get("kind"), previous.get("value")
                ) == target
            except ValueError:
                same_target = False
            if same_target:
                return True
        raise HomeAssistantError("target_refresh_conflict")

    async def remote_start(self, cp: GrowattChargePoint) -> str:
        authorization = self.coordinator.authorization
        if not authorization.begin_ha_remote_start(cp.id):
            return "Rejected"
        try:
            result = await cp.call(
                ocpp_call.RemoteStartTransaction(connector_id=1, id_tag=cp.id),
                suppress=False,
            )
        except Exception:
            authorization.cancel_ha_remote_start()
            raise
        status = _response_status(result)
        if status not in {"Accepted", "Rejected"}:
            authorization.cancel_ha_remote_start()
            raise ValueError("invalid_start_response")
        if status != "Accepted":
            authorization.cancel_ha_remote_start()
        return status

    async def reserve(self, cp: GrowattChargePoint, request: TargetRecord) -> str:
        result = await cp.call(
            ocpp_call.ReserveNow(
                connector_id=1,
                expiry_date=request["reservation_expiry"],
                id_tag=cp.id,
                reservation_id=request["reservation_id"],
            ),
            suppress=False,
        )
        status = _response_status(result)
        valid = {"Accepted", "Faulted", "Occupied", "Rejected", "Unavailable"}
        if status not in valid:
            raise ValueError("invalid_reservation_response")
        return status

    async def cancel_reservation(self, cp: GrowattChargePoint, reservation_id: int) -> str:
        result = await cp.call(
            ocpp_call.CancelReservation(reservation_id=reservation_id), suppress=False
        )
        status = _response_status(result)
        if status not in {"Accepted", "Rejected"}:
            raise ValueError("invalid_cancel_response")
        return status

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
        return self.block_reason(cp, activation)

    def pause_polling(self, seconds: float = _REQUEST_EXPIRY_SECONDS) -> None:
        pause_until = self.hass.loop.time() + seconds + self.coordinator._poll_pause_after_write
        self.hass.data[DOMAIN]["skip_polling_until"] = max(
            self.hass.data[DOMAIN].get("skip_polling_until", 0), pause_until
        )

    async def preview(self, service: ServiceCall) -> dict[str, Any]:
        return target_plan(self.parse(service.data), service.data.get("start", "now"))

    async def start(
        self, service: ServiceCall, *, activation: str = "remote"
    ) -> TargetRecord:
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
            cp = self.hass.data.get(DOMAIN, {}).get("charge_point")
            if reason := self.block_reason(cp, activation):
                raise HomeAssistantError(reason)
            request = {
                **target.diagnostic(),
                "request_id": uuid4().hex,
                "state": "queued",
                "updated_at": self.coordinator.now(),
                "enforcement_verified": NATIVE_STOP_VERIFIED[target.kind],
                "activation": {
                    "plug": "plug_and_charge",
                    "rfid": "rfid",
                    "remote": "remote_start",
                }[activation],
                "connection_started_at": self.coordinator.connection_started_at,
            }
            if replacing:
                request["previous_requests"] = _request_history(previous)
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
                    start=None if activation in {"plug", "rfid"} else lambda: self.remote_start(cp),
                    pause_seconds=_TARGET_START_PAUSE_SECONDS,
                    waiting_state=(
                        "target_accepted_waiting_for_plug"
                        if activation == "plug"
                        else "target_accepted_waiting_for_rfid"
                    ),
                )
                # A fast charger can emit StartTransaction before the
                # RemoteStart call unwinds and its callback observes the new
                # request state. Reconcile that race from coordinator truth.
                if (
                    request.get("state") == "start_accepted"
                    and self.coordinator.transaction_is_active
                ):
                    await save("active")
            finally:
                self._busy = False

        try:
            await self.coordinator.queue_write(execute)
        except Exception:  # noqa: BLE001 - persist sanitized outcome only
            self._busy = False
            await save("queue_failed")
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
            request.get("state") != "scheduled"
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
            await self.persist({**request, "state": "scheduled_missed"})
            return
        next_at = next_daily_start(
            start_at,
            now=self._now_utc(),
            time_zone=request["time_zone"],
        )
        updated = {
            **request,
            "state": "scheduled",
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
                or request.get("state") != "scheduled"
            ):
                return
            self._busy = True

        target = ChargingTarget.parse(request["kind"], request["value"])
        recurrence = request.get("recurrence", "once")
        activation = "daily_start" if recurrence == "daily" else "reserved_start"
        cp = self.hass.data.get(DOMAIN, {}).get("charge_point")
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
                    start=lambda: self.remote_start(cp),
                    # Growatt sends both calls at the reservation boundary. We
                    # wait only for target acceptance, then start immediately.
                    pause_seconds=0,
                )
                result = request.get("state", "outcome_unknown")
                if recurrence == "daily" and result in _DAILY_REPEATABLE_RESULTS:
                    if result == "start_accepted" and self.coordinator.transaction_is_active:
                        result = "charging"
                    await self.advance_daily(request, result)
                elif (
                    recurrence != "daily"
                    and result == "start_accepted"
                    and self.coordinator.transaction_is_active
                ):
                    await save("active")
            finally:
                self._busy = False

        try:
            await self.coordinator.queue_write(execute)
        except Exception:  # noqa: BLE001 - retained state explains uncertainty
            self._busy = False
            await save("queue_failed")

    async def schedule(self, service: ServiceCall) -> None:
        if service.data["entry_id"] != self.entry.entry_id:
            raise HomeAssistantError("wrong_charger_entry")
        target = self.parse(service.data)
        recurrence = service.data.get("recurrence", "once")
        try:
            start_at = parse_start_at(service.data["start_at"], now=self._now_utc())
        except ValueError as exc:
            raise HomeAssistantError(str(exc)) from None
        time_zone = str(getattr(getattr(self.hass, "config", None), "time_zone", "UTC"))

        async with self._lock:
            previous = self.coordinator.charging_target_request
            replacing = self.replacing_request(
                previous, service.data.get("replace_request_id"), target
            )
            if self._busy:
                raise HomeAssistantError("target_request_or_transaction_busy")
            cp = self.hass.data.get(DOMAIN, {}).get("charge_point")
            activation = "reserve" if recurrence == "once" else "remote"
            if reason := self.block_reason(cp, activation):
                raise HomeAssistantError(reason)
            request = {
                **target.diagnostic(),
                "request_id": uuid4().hex,
                "state": "reservation_queued" if recurrence == "once" else "scheduled",
                "scheduled_for": iso_utc(start_at),
                "time_zone": time_zone,
                "recurrence": recurrence,
                "updated_at": self.coordinator.now(),
                "enforcement_verified": NATIVE_STOP_VERIFIED[target.kind],
                "activation": (
                    "charger_reservation_remote_start"
                    if recurrence == "once"
                    else "daily_remote_start"
                ),
            }
            if recurrence == "once":
                request["reservation_id"] = secrets.randbelow(2_000_000_000) + 1
                try:
                    request["reservation_expiry"] = reservation_expiry(
                        start_at, time_zone
                    )
                except ValueError as exc:
                    raise HomeAssistantError(str(exc)) from None
            if replacing:
                request["previous_requests"] = _request_history(previous)
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
                    reserve=lambda: self.reserve(cp, request),
                    pause_seconds=_TARGET_RESERVATION_PAUSE_SECONDS,
                )
                if request.get("state") == "scheduled" and not self.arm_schedule(request):
                    await save("scheduled_missed")
            finally:
                self._busy = False

        try:
            await self.coordinator.queue_write(execute)
        except Exception:  # noqa: BLE001 - persist sanitized outcome only
            self._busy = False
            await save("queue_failed")
            raise HomeAssistantError("target_queue_failed") from None

    async def cancel_scheduled(self, service: ServiceCall) -> None:
        async with self._lock:
            request = self.coordinator.charging_target_request
            if (
                self._busy
                or not isinstance(request, dict)
                or request.get("request_id") != service.data["request_id"]
                or request.get("state") != "scheduled"
            ):
                raise HomeAssistantError("scheduled_target_not_cancellable")
            self.cancel_timer()
            if request.get("recurrence") == "daily":
                await self.persist(
                    {**request, "state": "scheduled_cancelled", "updated_at": self.coordinator.now()}
                )
                return
            reservation_id = request.get("reservation_id")
            cp = self.hass.data.get(DOMAIN, {}).get("charge_point")
            if (
                not isinstance(reservation_id, int)
                or not self.coordinator.connected
                or cp is None
                or self.hass.data.get(DOMAIN, {}).get("charge_point") is not cp
            ):
                raise HomeAssistantError("reservation_cancel_unavailable")
            request = {
                **request,
                "state": "cancellation_queued",
                "updated_at": self.coordinator.now(),
            }
            await self.persist(request)
            self._busy = True

        async def execute_cancel() -> None:
            nonlocal request
            try:
                request = {
                    **request,
                    "state": "sending_cancellation",
                    "updated_at": self.coordinator.now(),
                }
                await self.persist(request)
                status = await self.cancel_reservation(cp, reservation_id)
                request = {
                    **request,
                    "state": (
                        "scheduled_cancelled"
                        if status == "Accepted"
                        else "cancellation_rejected_reservation_may_remain"
                    ),
                    "updated_at": self.coordinator.now(),
                }
                await self.persist(request)
            except Exception:  # noqa: BLE001 - never leak OCPP payloads
                request = {
                    **request,
                    "state": "outcome_unknown",
                    "updated_at": self.coordinator.now(),
                }
                await self.persist(request)
            finally:
                self._busy = False

        try:
            await self.coordinator.queue_write(execute_cancel)
        except Exception:  # noqa: BLE001
            self._busy = False
            await self.persist({**request, "state": "queue_failed"})
            raise HomeAssistantError("target_queue_failed") from None

    async def status(self, service: ServiceCall) -> dict[str, TargetRecord | None]:
        return {"request": self.coordinator.charging_target_request}

    async def acknowledge(self, service: ServiceCall) -> None:
        async with self._lock:
            if self._busy or self.coordinator.transaction_is_active:
                raise HomeAssistantError("target_request_or_transaction_busy")
            request = self.coordinator.charging_target_request
            if isinstance(request, dict) and request.get("state") in {
                "reservation_queued",
                "scheduled",
                "cancellation_queued",
                "sending_cancellation",
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
                if request.get("last_run_state") != "start_accepted":
                    return
                await self.persist(
                    {**request, "last_run_state": "charging", "updated_at": self.coordinator.now()}
                )
                return
            if request.get("state") in {"start_accepted", *_WAITING_STATES}:
                await self.persist(
                    {**request, "state": "active", "updated_at": self.coordinator.now()}
                )

    async def transaction_stopped(self, *_args: object, **_kwargs: object) -> None:
        async with self._lock:
            request = self.coordinator.charging_target_request
            if not isinstance(request, dict):
                return
            if request.get("recurrence") == "daily":
                if request.get("last_run_state") != "charging":
                    return
                await self.persist(
                    {**request, "last_run_state": "completed", "updated_at": self.coordinator.now()}
                )
                return
            if request.get("state") == "active":
                await self.persist(
                    {**request, "state": "completed", "updated_at": self.coordinator.now()}
                )

    def close(self) -> None:
        """Release this entry's timer and transaction callbacks on unload."""
        self.cancel_timer()
        self.coordinator._cancel_charging_target_schedule = None
        self.coordinator._charging_target_transaction_started = None
        self.coordinator._charging_target_transaction_stopped = None


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
    hass.data.setdefault(DOMAIN, {})["target_runtime"] = runtime


def async_unload_target_runtime(hass: HomeAssistant) -> None:
    runtime = hass.data.get(DOMAIN, {}).pop("target_runtime", None)
    if runtime is not None:
        runtime.close()
    hass.data.get(DOMAIN, {}).pop("target_handlers", None)
