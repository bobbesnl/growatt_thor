"""Shared transaction-bound Stop execution for entities and automatic rules."""
from __future__ import annotations

import asyncio
import logging

from ..const import DOMAIN
from .session_controls import (
    REMOTE_START_COMMAND, REMOTE_STOP_COMMAND, SESSION_CONTROL_DEDUPE_KEY,
    STOP_CANCELLED_START_REASON, stop_revalidation_failure,
)
from ..runtime.write_queue import (
    TRANSACTION_CONTROL_WRITE_POLICY, ChargerConnectionUnavailable,
    ChargerRequestOutcomeUncertain, ChargerWriteResult,
)

_LOGGER = logging.getLogger(__name__)


def _command_state(coordinator, action, state):
    """Report command acceptance separately from physical charger state."""
    coordinator.dashboard_command = {
        "action": action,
        "state": state,
        "updated_at": coordinator.now(),
    }
    coordinator.async_set_updated_data(True)



class StopChargingCommand:
    """Use the coordinator's existing queue, never a second command owner."""

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.hass = coordinator.hass

    def _stop_revalidation_failure(
        self,
        expected_transaction_id: int,
    ) -> str | None:
        """Keep a delayed Stop bound to the transaction it was created for."""
        return stop_revalidation_failure(
            expected_transaction_id=expected_transaction_id,
            current_transaction_id=self.coordinator.transaction_id,
            transaction_active=self.coordinator.transaction_is_active,
        )

    async def async_request(self, *, auto_guard=None) -> None:
        """Stop a charging session via queue."""
        from ..runtime.action_errors import (
            async_require_command_completion,
            raise_action_validation,
            raise_charger_disconnected,
        )
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
                "⏹️ Cancelled %d unsent start command(s); no active "
                "transaction needs an OCPP Stop",
                cancelled_starts,
            )
            return

        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if not charge_point:
            _LOGGER.warning("Cannot stop charging: charger not connected")
            raise_charger_disconnected()

        if transaction_id is None or not transaction_active:
            _LOGGER.warning(
                "⚠️ Cannot stop charging: no active session (status=%s)",
                self.coordinator.status
            )
            raise_action_validation("no_active_transaction")

        _LOGGER.info(
            "🔘 Queueing stop charging command (transaction_id=%s)",
            transaction_id,
        )

        _command_state(self.coordinator, "stop", "queued")
        handle = await self.coordinator.queue_write(
            self._stop_charging,
            charge_point,
            transaction_id,
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
        await async_require_command_completion(handle)

    async def _stop_charging(
        self,
        charge_point,
        transaction_id: int,
    ) -> ChargerWriteResult:
        """Stop charging command (runs inside write-queue)."""
        if (
            reason := self._stop_revalidation_failure(transaction_id)
        ) is not None:
            _LOGGER.warning("Skipping stale stop charging command: %s", reason)
            _command_state(self.coordinator, "stop", "rejected")
            return ChargerWriteResult.skipped(reason)
        _command_state(self.coordinator, "stop", "sending")
        self.coordinator.record_stop_requested()
        try:
            result = await charge_point.remote_stop_transaction(
                transaction_id=transaction_id
            )

            if result.get("status") == "Accepted":
                _command_state(self.coordinator, "stop", "accepted")
                _LOGGER.info("✅ Charging session stopped successfully")
                self.hass.async_create_task(self._post_status_update())
                self.coordinator.async_set_updated_data(True)
                return ChargerWriteResult.success(result.get("status"))
            else:
                _command_state(self.coordinator, "stop", "rejected")
                _LOGGER.error("❌ Stop charging rejected: %s", result.get("status"))
                return ChargerWriteResult.failed(
                    "charger_rejected",
                    result.get("status"),
                )

        except ChargerConnectionUnavailable:
            _command_state(self.coordinator, "stop", "error")
            raise
        except ChargerRequestOutcomeUncertain as exc:
            _command_state(self.coordinator, "stop", "uncertain")
            return ChargerWriteResult.uncertain(str(exc))
        except Exception as exc:
            _command_state(self.coordinator, "stop", "error")
            _LOGGER.error("❌ Failed to stop charging: %s", exc, exc_info=True)
            return ChargerWriteResult.failed("unexpected_error")

    async def _post_status_update(self):
        """Trigger a status update on whichever connection is current later."""
        await asyncio.sleep(2)
        try:
            # See the matching start helper: delayed work must not retain a
            # websocket that may have been superseded during the wait.
            charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
            if charge_point is None:
                return
            await charge_point.trigger_status()
            self.coordinator.async_set_updated_data(True)
        except Exception as exc:
            _LOGGER.error("❌ Failed to trigger status after stop: %s", exc, exc_info=True)

