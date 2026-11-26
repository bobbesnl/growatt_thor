"""Guarded charger commands for entities and automatic rules."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from functools import partial

from ..const import DOMAIN as DOMAIN
from ..ocpp.core.status import normalize_ocpp_status
from ..runtime.action_errors import (
    async_require_command_completion,
    raise_action_validation,
    raise_charger_disconnected,
    raise_write_blocked,
)
from ..runtime.keys import ACTIVE_CHARGE_POINT
from ..runtime.write_results import (
    TRANSACTION_CONTROL_WRITE_POLICY,
    VOLATILE_CONTROL_WRITE_POLICY,
    ChargerCommandHandle,
    ChargerCommandResult,
    ChargerConnectionUnavailable,
    ChargerRequestOutcomeUncertain,
    ChargerWriteResult,
)
from .contracts import CommandOwner, RestartTransport, TransactionTransport
from .control_capabilities import charger_write_block_reason
from .start_stop_rules import (
    REMOTE_START_COMMAND,
    REMOTE_STOP_COMMAND,
    SESSION_CONTROL_DEDUPE_KEY,
    STOP_CANCELLED_START_REASON,
    start_revalidation_failure,
    stop_revalidation_failure,
    target_blocks_manual_start,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_ID_TAG = "12345678"  # Growatt handshake key
STATUS_TRIGGER_DELAY_SECONDS = 2


class RestartChargerCommand:
    """A manual reset that expires on the connection it was requested for."""

    def __init__(self, coordinator: CommandOwner) -> None:
        self.coordinator = coordinator
        # Queue deduplication replaces unsent work. A reset must reject another
        # request even while its first OCPP reply is outstanding.
        self._pending = False

    def _revalidate(self, charge_point: RestartTransport | None) -> str | None:
        coordinator = self.coordinator
        if (
            not coordinator.connected
            or charge_point is None
            or coordinator.runtime_data.get(ACTIVE_CHARGE_POINT) is not charge_point
        ):
            return "charger_disconnected"
        if coordinator.charger_reboot_pending:
            return "charger_rebooting"
        if coordinator.transaction_is_active:
            return "active_transaction"
        # Require a known state, and keep charger-side reservations intact.
        if normalize_ocpp_status(coordinator.status) in {None, "reserved"}:
            return "restart_not_ready"
        return None

    @property
    def write_block_reason(self) -> str | None:
        if self._pending:
            return "restart_in_progress"
        return self._revalidate(self.coordinator.runtime_data.get(ACTIVE_CHARGE_POINT))

    async def async_request(self) -> None:
        if (reason := self.write_block_reason) is not None:
            raise_write_blocked(reason)
        charge_point: RestartTransport = self.coordinator.runtime_data[ACTIVE_CHARGE_POINT]
        queued_block_reason = partial(self._revalidate, charge_point)
        loop = self.coordinator.hass.loop
        deadline = loop.time() + VOLATILE_CONTROL_WRITE_POLICY.expires_after

        def check_at_gate() -> ChargerWriteResult | None:
            # Time spent waiting for the OCPP gate also counts towards expiry.
            if loop.time() >= deadline:
                return ChargerWriteResult.expired()
            if (reason := queued_block_reason()) is not None:
                return ChargerWriteResult.skipped(reason)
            return None

        self._pending = True
        handle: ChargerCommandHandle | None = None
        try:
            handle = await self.coordinator.queue_write(
                self._reset,
                charge_point,
                check_at_gate=check_at_gate,
                command_name="Reset",
                requires_connection=True,
                rate_limited=False,
                policy=VOLATILE_CONTROL_WRITE_POLICY,
                revalidate=queued_block_reason,
            )
        finally:
            if handle is None:
                self._clear_pending()
        handle.add_done_callback(self._clear_pending)
        self.coordinator.async_set_updated_data(True)
        await async_require_command_completion(handle)

    def _clear_pending(self, _result: ChargerCommandResult | None = None) -> None:
        # A HA caller can cancel or time out before the queue finishes.
        self._pending = False
        self.coordinator.async_set_updated_data(True)

    @staticmethod
    async def _reset(
        charge_point: RestartTransport, *, check_at_gate: Callable[[], ChargerWriteResult | None]
    ) -> ChargerWriteResult:
        return await charge_point.soft_reset(check_at_gate=check_at_gate)


def command_state(
    coordinator: CommandOwner, action: str, state: str, *, reason: str | None = None
) -> None:
    """Report command acceptance separately from physical charger state."""
    coordinator.dashboard_command = {
        "action": action,
        "state": state,
        "updated_at": coordinator.now(),
        **({"reason": reason} if reason else {}),
    }
    coordinator.async_set_updated_data(True)


class StopChargingCommand:
    """Use the coordinator's existing queue, never a second command owner."""

    def __init__(self, coordinator: CommandOwner) -> None:
        self.coordinator = coordinator
        self.hass = coordinator.hass

    def _stop_revalidation_failure(
        self,
        expected_transaction_id: int | str,
    ) -> str | None:
        """Keep a delayed Stop bound to the transaction it was created for."""
        return stop_revalidation_failure(
            expected_transaction_id=expected_transaction_id,
            current_transaction_id=self.coordinator.transaction_id,
            transaction_active=self.coordinator.transaction_is_active,
        )

    async def async_request(
        self,
        *,
        auto_guard: Callable[[], str | None] | None = None,
        stop_reason: str | None = None,
        on_result: Callable[[ChargerCommandResult], None] | None = None,
    ) -> None:
        """Stop a charging session via queue."""

        # A Stop pressed before a queued Start reaches OCPP means "do not
        # start".  Cancelling that local intent is useful even if the charger
        # disconnected in the meantime and must not manufacture a Stop for ID
        # 0.  An already executing Start is intentionally not cancellable: once
        # OCPP may have received it, only observed transaction state is safe.
        cancelled_starts = self.coordinator.cancel_queued_writes(
            dedupe_key=SESSION_CONTROL_DEDUPE_KEY,
            command_name=REMOTE_START_COMMAND,
            reason=STOP_CANCELLED_START_REASON,
        )
        transaction_id = self.coordinator.transaction_id
        transaction_active = self.coordinator.transaction_is_active

        if cancelled_starts and not transaction_active:
            _LOGGER.info(
                "Cancelled %d unsent start command(s); no active transaction needs an OCPP Stop",
                cancelled_starts,
            )
            return

        charge_point = self.coordinator.runtime_data.get(ACTIVE_CHARGE_POINT)
        if not charge_point:
            _LOGGER.warning("Cannot stop charging: charger not connected")
            raise_charger_disconnected()

        if transaction_id is None or not transaction_active:
            _LOGGER.warning(
                "Cannot stop charging: no active session (status=%s)",
                self.coordinator.status,
            )
            raise_action_validation("no_active_transaction")

        _LOGGER.info(
            "Queueing stop charging command (transaction_id=%s)",
            transaction_id,
        )

        command_state(self.coordinator, "stop", "queued")
        handle = await self.coordinator.queue_write(
            self._stop_charging,
            charge_point,
            transaction_id,
            *([stop_reason] if stop_reason else []),
            # A valid Stop replaces only an unsent Start.  Conversely, public
            # Start is blocked while this transaction remains active, so it
            # cannot erase a still-valid Stop for the running session.
            dedupe_key=SESSION_CONTROL_DEDUPE_KEY,
            priority=True,
            rate_limited=False,
            command_name=REMOTE_STOP_COMMAND,
            requires_connection=True,
            policy=TRANSACTION_CONTROL_WRITE_POLICY,
            revalidate=lambda: (
                self._stop_revalidation_failure(transaction_id)
                or (auto_guard() if auto_guard is not None else None)
            ),
        )
        if on_result is not None:
            handle.add_done_callback(on_result)
        await async_require_command_completion(handle)

    async def _stop_charging(
        self,
        charge_point: TransactionTransport,
        transaction_id: int | str,
        stop_reason: str | None = None,
    ) -> ChargerWriteResult:
        """Stop charging command (runs inside write-queue)."""
        if (reason := self._stop_revalidation_failure(transaction_id)) is not None:
            _LOGGER.warning("Skipping stale stop charging command: %s", reason)
            command_state(self.coordinator, "stop", "rejected")
            return ChargerWriteResult.skipped(reason)
        command_state(self.coordinator, "stop", "sending")
        if stop_reason:
            self.coordinator.record_stop_requested(reason=stop_reason)
        else:
            self.coordinator.record_stop_requested()
        try:
            result = await charge_point.remote_stop_transaction(transaction_id=transaction_id)

            if result.get("status") == "Accepted":
                command_state(self.coordinator, "stop", "accepted")
                _LOGGER.info("Charging session stopped successfully")
                self.hass.async_create_task(self._post_status_update())
                self.coordinator.async_set_updated_data(True)
                return ChargerWriteResult.success(result.get("status"))
            else:
                command_state(self.coordinator, "stop", "rejected")
                _LOGGER.error("Stop charging rejected: %s", result.get("status"))
                return ChargerWriteResult.failed(
                    "charger_rejected",
                    result.get("status"),
                )

        except ChargerConnectionUnavailable:
            command_state(self.coordinator, "stop", "error")
            raise
        except ChargerRequestOutcomeUncertain as exc:
            command_state(self.coordinator, "stop", "uncertain")
            return ChargerWriteResult.uncertain(str(exc))
        except Exception as exc:
            # Convert unexpected command failures to the existing terminal write result.
            command_state(self.coordinator, "stop", "error")
            _LOGGER.error("Failed to stop charging: %s", exc, exc_info=True)
            return ChargerWriteResult.failed("unexpected_error")

    async def _post_status_update(self) -> None:
        """Trigger a status update on whichever connection is current later."""
        await asyncio.sleep(STATUS_TRIGGER_DELAY_SECONDS)
        try:
            # See the matching start helper: delayed work must not retain a
            # websocket that may have been superseded during the wait.
            charge_point = self.coordinator.runtime_data.get(ACTIVE_CHARGE_POINT)
            if charge_point is None:
                return
            await charge_point.trigger_status()
            self.coordinator.async_set_updated_data(True)
        except Exception as exc:
            # A failed follow-up read must not escape this background task.
            _LOGGER.error("Failed to trigger status after stop: %s", exc, exc_info=True)


class StartChargingCommand:
    """Submit a revalidated Start through the existing charger write owner."""

    def __init__(self, coordinator: CommandOwner) -> None:
        self.coordinator = coordinator
        self.hass = coordinator.hass

    @property
    def write_block_reason(self) -> str | None:
        if target_blocks_manual_start(self.coordinator.charging_target_request):
            return "native_target_requires_reconciliation"
        return charger_write_block_reason(
            connected=self.coordinator.connected,
            charger_faulted=self.coordinator.charger_is_faulted,
            reboot_pending=self.coordinator.charger_reboot_pending,
        )

    def _start_revalidation_failure(self) -> str | None:
        """Return why a delayed start no longer represents a valid intent."""
        if (reason := self.write_block_reason) is not None:
            return reason
        return start_revalidation_failure(
            charger_faulted=self.coordinator.charger_is_faulted,
            transaction_active=self.coordinator.transaction_is_active,
        )

    async def async_request(self) -> None:
        """Start a charging session via queue."""
        if (block_reason := self.write_block_reason) is not None:
            _LOGGER.warning("Cannot start charging: %s", block_reason)
            raise_write_blocked(block_reason)
        charge_point = self.coordinator.runtime_data.get(ACTIVE_CHARGE_POINT)
        if not charge_point:
            _LOGGER.warning("Cannot start charging: charger not connected")
            raise_charger_disconnected()

        if self.coordinator.transaction_is_active:
            _LOGGER.warning(
                "Cannot start charging: session already active (transaction_id=%s)",
                self.coordinator.transaction_id,
            )
            raise_action_validation("charging_already_active")

        _LOGGER.info("Queueing priority start charging command")
        command_state(self.coordinator, "start", "queued")
        handle = await self.coordinator.queue_write(
            self._start_charging,
            charge_point,
            # Start and Stop share one logical queue lane.  A later, valid
            # opposing intent can therefore replace work that was never sent.
            dedupe_key=SESSION_CONTROL_DEDUPE_KEY,
            priority=True,
            rate_limited=False,
            command_name=REMOTE_START_COMMAND,
            requires_connection=True,
            policy=VOLATILE_CONTROL_WRITE_POLICY,
            revalidate=self._start_revalidation_failure,
        )
        # Start/Stop are priority controls rather than slow configuration
        # edits, so their HA actions can wait for a bounded physical outcome.
        await async_require_command_completion(handle)

    async def _start_charging(self, charge_point: TransactionTransport) -> ChargerWriteResult:
        """Start charging command (runs inside write-queue)."""
        if (reason := self._start_revalidation_failure()) is not None:
            _LOGGER.warning("Skipping queued start charging: %s", reason)
            command_state(self.coordinator, "start", "rejected")
            return ChargerWriteResult.skipped(reason)
        command_state(self.coordinator, "start", "sending")
        try:
            result = await charge_point.remote_start_transaction(
                connector_id=1, id_tag=DEFAULT_ID_TAG
            )

            if result.get("status") == "Accepted":
                command_state(self.coordinator, "start", "accepted")
                _LOGGER.info("Charging session started successfully")
                self.hass.async_create_task(self._post_status_update())
                self.coordinator.async_set_updated_data(True)
                return ChargerWriteResult.success(result.get("status"))
            else:
                reason = (
                    "local_authorization_denied"
                    if result.get("reason") == "local_authorization_denied"
                    else "charger_rejected"
                )
                command_state(self.coordinator, "start", "rejected", reason=reason)
                _LOGGER.warning("Start charging rejected: %s", reason)
                return ChargerWriteResult.failed(
                    reason,
                    result.get("status"),
                )

        except ChargerConnectionUnavailable:
            command_state(self.coordinator, "start", "error")
            raise
        except ChargerRequestOutcomeUncertain as exc:
            command_state(self.coordinator, "start", "uncertain")
            return ChargerWriteResult.uncertain(str(exc))
        except Exception as exc:
            # Convert unexpected command failures to the existing terminal write result.
            command_state(self.coordinator, "start", "error")
            _LOGGER.error("Failed to start charging: %s", exc, exc_info=True)
            return ChargerWriteResult.failed("unexpected_error")

    async def _post_status_update(self) -> None:
        """Trigger a status update on whichever connection is current later."""
        await asyncio.sleep(STATUS_TRIGGER_DELAY_SECONDS)
        try:
            # Capturing the charge point used for the original command is unsafe:
            # the THOR can reconnect during this delay and replace its socket.
            charge_point = self.coordinator.runtime_data.get(ACTIVE_CHARGE_POINT)
            if charge_point is None:
                return
            await charge_point.trigger_status()
            self.coordinator.async_set_updated_data(True)
        except Exception as exc:
            # A failed follow-up read must not escape this background task.
            _LOGGER.error("Failed to trigger status after start: %s", exc, exc_info=True)
