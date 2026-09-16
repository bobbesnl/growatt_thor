"""Button entities for Growatt THOR configuration."""
from __future__ import annotations

import logging
import asyncio

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .action_errors import (
    raise_action_validation,
    raise_charger_disconnected,
    raise_write_blocked,
)
from .charging_controls import (
    ChargingControl,
    charger_write_block_reason,
    control_write_block_reason,
)
from .const import DOMAIN
from .pv_linkage import (
    build_pv_linkage_writes,
    draft_validation_errors,
)
from .pv_linkage_apply import apply_pv_linkage_writes
from .session_controls import (
    REMOTE_START_COMMAND,
    REMOTE_STOP_COMMAND,
    SESSION_CONTROL_DEDUPE_KEY,
    STOP_CANCELLED_START_REASON,
    start_revalidation_failure,
    stop_revalidation_failure,
)
from .write_queue import (
    CONFIGURATION_WRITE_POLICY,
    TRANSACTION_CONTROL_WRITE_POLICY,
    VOLATILE_CONTROL_WRITE_POLICY,
    ChargerConnectionUnavailable,
    ChargerRequestOutcomeUncertain,
    ChargerWriteResult,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_ID_TAG = "12345678"  # Growatt handshake key


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Growatt THOR button entities."""
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities([
        StartChargingButton(coordinator, entry),
        StopChargingButton(coordinator, entry),
        ApplyPvLinkageButton(coordinator, entry),
    ])


# ─────────────────────────────
# Start Charging Button
# ─────────────────────────────

class StartChargingButton(CoordinatorEntity, ButtonEntity):
    """Button to start a charging session."""

    _attr_has_entity_name = True
    _attr_translation_key = "start_charging"
    _attr_icon = "mdi:play-circle"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_start_charging"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }
        self.hass = coordinator.hass

    @property
    def _write_block_reason(self) -> str | None:
        return charger_write_block_reason(
            connected=self.coordinator.connected,
            charger_faulted=self.coordinator.charger_is_faulted,
        )

    @property
    def available(self):
        return super().available and self._write_block_reason is None

    def _start_revalidation_failure(self) -> str | None:
        """Return why a delayed start no longer represents a valid intent."""
        return start_revalidation_failure(
            charger_faulted=self.coordinator.charger_is_faulted,
            transaction_active=self.coordinator.transaction_is_active,
        )

    async def async_press(self) -> None:
        """Start a charging session via queue."""
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning("Cannot start charging: %s", block_reason)
            raise_write_blocked(block_reason)
        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if not charge_point:
            _LOGGER.warning("Cannot start charging: charger not connected")
            raise_charger_disconnected()

        if self.coordinator.transaction_is_active:
            _LOGGER.warning(
                "⚠️ Cannot start charging: session already active (transaction_id=%s)",
                self.coordinator.transaction_id
            )
            raise_action_validation("charging_already_active")

        _LOGGER.info("🔘 Queueing priority start charging command")
        await self.coordinator.queue_write(
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

    async def _start_charging(self, charge_point) -> ChargerWriteResult:
        """Start charging command (runs inside write-queue)."""
        if (reason := self._start_revalidation_failure()) is not None:
            _LOGGER.warning("Skipping queued start charging: %s", reason)
            return ChargerWriteResult.skipped(reason)
        try:
            result = await charge_point.remote_start_transaction(
                connector_id=1,
                id_tag=DEFAULT_ID_TAG
            )

            if result.get("status") == "Accepted":
                _LOGGER.info("✅ Charging session started successfully")
                self.hass.async_create_task(self._post_status_update())
                self.coordinator.async_set_updated_data(True)
                return ChargerWriteResult.success(result.get("status"))
            else:
                _LOGGER.error("❌ Start charging rejected: %s", result.get("status"))
                return ChargerWriteResult.failed(
                    "charger_rejected",
                    result.get("status"),
                )

        except ChargerConnectionUnavailable:
            raise
        except ChargerRequestOutcomeUncertain as exc:
            return ChargerWriteResult.uncertain(str(exc))
        except Exception as exc:
            _LOGGER.error("❌ Failed to start charging: %s", exc, exc_info=True)
            return ChargerWriteResult.failed("unexpected_error")

    async def _post_status_update(self):
        """Trigger a status update on whichever connection is current later."""
        await asyncio.sleep(2)
        try:
            # Capturing the charge point used for the original command is unsafe:
            # the THOR can reconnect during this delay and replace its socket.
            charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
            if charge_point is None:
                return
            await charge_point.trigger_status()
            self.coordinator.async_set_updated_data(True)
        except Exception as exc:
            _LOGGER.error("❌ Failed to trigger status after start: %s", exc, exc_info=True)


# ─────────────────────────────
# Stop Charging Button
# ─────────────────────────────

class StopChargingButton(CoordinatorEntity, ButtonEntity):
    """Button to stop a charging session."""

    _attr_has_entity_name = True
    _attr_translation_key = "stop_charging"
    _attr_icon = "mdi:stop-circle"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_stop_charging"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }
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

    async def async_press(self) -> None:
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

        await self.coordinator.queue_write(
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
            revalidate=lambda: self._stop_revalidation_failure(
                transaction_id
            ),
        )

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
            return ChargerWriteResult.skipped(reason)
        try:
            result = await charge_point.remote_stop_transaction(
                transaction_id=transaction_id
            )

            if result.get("status") == "Accepted":
                _LOGGER.info("✅ Charging session stopped successfully")
                self.hass.async_create_task(self._post_status_update())
                self.coordinator.async_set_updated_data(True)
                return ChargerWriteResult.success(result.get("status"))
            else:
                _LOGGER.error("❌ Stop charging rejected: %s", result.get("status"))
                return ChargerWriteResult.failed(
                    "charger_rejected",
                    result.get("status"),
                )

        except ChargerConnectionUnavailable:
            raise
        except ChargerRequestOutcomeUncertain as exc:
            return ChargerWriteResult.uncertain(str(exc))
        except Exception as exc:
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


class ApplyPvLinkageButton(CoordinatorEntity, ButtonEntity):
    """Apply the complete local PV Linkage boost draft."""

    _attr_has_entity_name = True
    _attr_translation_key = "apply_pv_linkage"
    _attr_icon = "mdi:check-bold"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self.hass = coordinator.hass
        self._attr_unique_id = f"{entry.entry_id}_apply_pv_linkage"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }

    @property
    def _write_block_reason(self) -> str | None:
        return control_write_block_reason(
            ChargingControl.SOLAR_BOOST,
            self.coordinator.configuration_values,
            connected=self.coordinator.connected,
            transaction_active=self.coordinator.transaction_is_active,
            charger_faulted=self.coordinator.charger_is_faulted,
        )

    @property
    def _validation_errors(self) -> tuple[str, ...]:
        draft = self.coordinator.pv_linkage_draft()
        return (
            ("draft_not_initialized",)
            if draft is None
            else draft_validation_errors(draft)
        )

    @property
    def available(self):
        return (
            super().available
            and self._write_block_reason is None
            and not self._validation_errors
            and self.coordinator.pv_linkage_draft_dirty
        )

    @property
    def extra_state_attributes(self):
        last_apply = self.coordinator.pv_linkage_apply_result
        return {
            "information": "details",
            "pending_changes": self.coordinator.pv_linkage_draft_dirty,
            "validation_errors": list(self._validation_errors),
            "last_apply": (
                last_apply.as_dict() if last_apply is not None else None
            ),
        }

    async def async_press(self) -> None:
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning(
                "Cannot apply PV Linkage configuration: %s",
                block_reason,
            )
            raise_write_blocked(block_reason)

        draft = self.coordinator.pv_linkage_draft()
        if draft is None or (errors := draft_validation_errors(draft)):
            _LOGGER.warning(
                "Cannot apply incomplete PV Linkage configuration: %s",
                errors if draft is not None else ("draft_not_initialized",),
            )
            raise_action_validation(
                "invalid_pv_linkage_draft",
                placeholders={
                    "errors": ", ".join(
                        errors
                        if draft is not None
                        else ("draft_not_initialized",)
                    ),
                },
            )

        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if charge_point is None:
            _LOGGER.warning("Cannot apply PV Linkage: charger not connected")
            raise_charger_disconnected()

        writes = build_pv_linkage_writes(draft, now=dt_util.now())
        await self.coordinator.queue_write(
            self._apply_writes,
            charge_point,
            draft,
            writes,
            dedupe_key="pv_linkage_compound",
            command_name="ApplyPvLinkage",
            requires_connection=True,
            policy=CONFIGURATION_WRITE_POLICY,
        )

    async def _apply_writes(
        self,
        charge_point,
        draft,
        writes,
    ) -> ChargerWriteResult:
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning(
                "Skipping queued PV Linkage configuration: %s",
                block_reason,
            )
            return ChargerWriteResult.skipped(block_reason)
        return await apply_pv_linkage_writes(
            coordinator=self.coordinator,
            charge_point=charge_point,
            draft=draft,
            writes=writes,
        )
