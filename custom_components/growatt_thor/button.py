"""Button entities for Growatt THOR configuration."""
from __future__ import annotations

import logging
import asyncio

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .runtime.action_errors import (
    async_require_command_completion,
    raise_action_validation,
    raise_charger_disconnected,
    raise_write_blocked,
)
from .charging.controls import (
    ChargingControl,
    charger_write_block_reason,
    control_write_block_reason,
)
from .charging.commands import StopChargingCommand, _command_state
from .const import DOMAIN
from .charging.pv_linkage import (
    build_pv_linkage_writes,
    draft_validation_errors,
)
from .charging.pv_apply import apply_pv_linkage_writes
from .charging.session_controls import (
    REMOTE_START_COMMAND,
    SESSION_CONTROL_DEDUPE_KEY,
    start_revalidation_failure,
    target_blocks_manual_start,
)
from .runtime.write_queue import (
    CONFIGURATION_WRITE_POLICY,
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
        if target_blocks_manual_start(getattr(self.coordinator, "charging_target_request", None)):
            return "native_target_requires_reconciliation"
        return charger_write_block_reason(
            connected=self.coordinator.connected,
            charger_faulted=self.coordinator.charger_is_faulted,
        )

    @property
    def available(self):
        return super().available and self._write_block_reason is None

    def _start_revalidation_failure(self) -> str | None:
        """Return why a delayed start no longer represents a valid intent."""
        if (reason := self._write_block_reason) is not None:
            return reason
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
        _command_state(self.coordinator, "start", "queued")
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

    async def _start_charging(self, charge_point) -> ChargerWriteResult:
        """Start charging command (runs inside write-queue)."""
        if (reason := self._start_revalidation_failure()) is not None:
            _LOGGER.warning("Skipping queued start charging: %s", reason)
            _command_state(self.coordinator, "start", "rejected")
            return ChargerWriteResult.skipped(reason)
        _command_state(self.coordinator, "start", "sending")
        try:
            result = await charge_point.remote_start_transaction(
                connector_id=1,
                id_tag=DEFAULT_ID_TAG
            )

            if result.get("status") == "Accepted":
                _command_state(self.coordinator, "start", "accepted")
                _LOGGER.info("✅ Charging session started successfully")
                self.hass.async_create_task(self._post_status_update())
                self.coordinator.async_set_updated_data(True)
                return ChargerWriteResult.success(result.get("status"))
            else:
                _command_state(self.coordinator, "start", "rejected")
                _LOGGER.error("❌ Start charging rejected: %s", result.get("status"))
                return ChargerWriteResult.failed(
                    "charger_rejected",
                    result.get("status"),
                )

        except ChargerConnectionUnavailable:
            _command_state(self.coordinator, "start", "error")
            raise
        except ChargerRequestOutcomeUncertain as exc:
            _command_state(self.coordinator, "start", "uncertain")
            return ChargerWriteResult.uncertain(str(exc))
        except Exception as exc:
            _command_state(self.coordinator, "start", "error")
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

    async def async_press(self) -> None:
        """Delegate the entity action to the common command boundary."""
        await StopChargingCommand(self.coordinator).async_request()


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
        handle = await self.coordinator.queue_write(
            self._apply_writes,
            charge_point,
            draft,
            writes,
            dedupe_key="pv_linkage_compound",
            command_name="ApplyPvLinkage",
            requires_connection=True,
            policy=CONFIGURATION_WRITE_POLICY,
        )
        # A compound Apply must not return success merely because it entered
        # the queue; partial and uncertain physical outcomes are surfaced.
        await async_require_command_completion(handle)

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
