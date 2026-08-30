"""Button entities for Growatt THOR configuration."""
from __future__ import annotations

import logging
import asyncio

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from ocpp.v16.enums import ConfigurationStatus, DataTransferStatus

from .charging_controls import (
    ChargingControl,
    charger_write_block_reason,
    control_write_block_reason,
)
from .configuration_control import async_confirm_configuration
from .const import DOMAIN
from .pv_linkage import (
    ConfigurationWrite,
    DataTransferWrite,
    build_pv_linkage_writes,
    draft_validation_errors,
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

    async def async_press(self) -> None:
        """Start a charging session via queue."""
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning("Cannot start charging: %s", block_reason)
            return
        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if not charge_point:
            _LOGGER.warning("Cannot start charging: charger not connected")
            return

        if self.coordinator.status == "Charging":
            _LOGGER.warning(
                "⚠️ Cannot start charging: session already active (transaction_id=%s)",
                self.coordinator.transaction_id
            )
            return

        _LOGGER.info("🔘 Queueing start charging command")
        await self.coordinator.queue_write(self._start_charging, charge_point)

    async def _start_charging(self, charge_point):
        """Start charging command (runs inside write-queue)."""
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning("Skipping queued start charging: %s", block_reason)
            return
        try:
            result = await charge_point.remote_start_transaction(
                connector_id=1,
                id_tag=DEFAULT_ID_TAG
            )

            if result.get("status") == "Accepted":
                _LOGGER.info("✅ Charging session started successfully")
                self.hass.async_create_task(self._post_status_update(charge_point))
                self.coordinator.async_set_updated_data(True)
            else:
                _LOGGER.error("❌ Start charging rejected: %s", result.get("status"))

        except Exception as exc:
            _LOGGER.error("❌ Failed to start charging: %s", exc, exc_info=True)

    async def _post_status_update(self, charge_point):
        """Trigger a status update after a short delay (outside write-queue)."""
        await asyncio.sleep(2)
        try:
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
        """Stop a charging session via queue."""
        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if not charge_point:
            _LOGGER.warning("Cannot stop charging: charger not connected")
            return

        is_charging = self.coordinator.status == "Charging"
        transaction_id = self.coordinator.transaction_id

        if not is_charging and transaction_id is None:
            _LOGGER.warning(
                "⚠️ Cannot stop charging: no active session (status=%s)",
                self.coordinator.status
            )
            return

        # Gebruik transaction_id 0 als fallback (stop huidige sessie)
        tid = transaction_id if transaction_id is not None else 0

        if transaction_id is None:
            _LOGGER.info(
                "🔘 Queueing stop charging (using fallback transaction_id=0, status=%s)",
                self.coordinator.status
            )
        else:
            _LOGGER.info("🔘 Queueing stop charging command (transaction_id=%s)", tid)

        await self.coordinator.queue_write(self._stop_charging, charge_point, tid)

    async def _stop_charging(self, charge_point, transaction_id: int):
        """Stop charging command (runs inside write-queue)."""
        try:
            result = await charge_point.remote_stop_transaction(
                transaction_id=transaction_id
            )

            if result.get("status") == "Accepted":
                _LOGGER.info("✅ Charging session stopped successfully")
                self.hass.async_create_task(self._post_status_update(charge_point))
                self.coordinator.async_set_updated_data(True)
            else:
                _LOGGER.error("❌ Stop charging rejected: %s", result.get("status"))

        except Exception as exc:
            _LOGGER.error("❌ Failed to stop charging: %s", exc, exc_info=True)

    async def _post_status_update(self, charge_point):
        """Trigger a status update after a short delay (outside write-queue)."""
        await asyncio.sleep(2)
        try:
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
        return {
            "information": "details",
            "pending_changes": self.coordinator.pv_linkage_draft_dirty,
            "validation_errors": list(self._validation_errors),
        }

    async def async_press(self) -> None:
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning(
                "Cannot apply PV Linkage configuration: %s",
                block_reason,
            )
            return

        draft = self.coordinator.pv_linkage_draft()
        if draft is None or (errors := draft_validation_errors(draft)):
            _LOGGER.warning(
                "Cannot apply incomplete PV Linkage configuration: %s",
                errors if draft is not None else ("draft_not_initialized",),
            )
            return

        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if charge_point is None:
            _LOGGER.warning("Cannot apply PV Linkage: charger not connected")
            return

        writes = build_pv_linkage_writes(draft, now=dt_util.now())
        await self.coordinator.queue_write(
            self._apply_writes,
            charge_point,
            writes,
            dedupe_key="pv_linkage_compound",
        )

    async def _apply_writes(self, charge_point, writes) -> None:
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning(
                "Skipping queued PV Linkage configuration: %s",
                block_reason,
            )
            return

        accepted_configuration = False
        for write in writes:
            if isinstance(write, ConfigurationWrite):
                self.coordinator.begin_configuration_write(
                    write.key,
                    write.value,
                )
                result = await charge_point.change_configuration(
                    write.key,
                    write.value,
                )
                accepted = result in {
                    ConfigurationStatus.accepted,
                    ConfigurationStatus.reboot_required,
                }
                self.coordinator.acknowledge_configuration_write(
                    write.key,
                    accepted=accepted,
                    result=result,
                )
                if not accepted:
                    _LOGGER.error(
                        "PV Linkage write %s was rejected: %s",
                        write.key,
                        result,
                    )
                    return
                self.coordinator.update_configuration_value(
                    write.key,
                    write.value,
                )
                accepted_configuration = True
                continue

            if isinstance(write, DataTransferWrite):
                result = await charge_point.send_data_transfer(
                    vendor_id=write.vendor_id,
                    message_id=write.message_id,
                    data=write.data,
                )
                if result != DataTransferStatus.accepted:
                    _LOGGER.error(
                        "PV Linkage DataTransfer %s was rejected: %s",
                        write.message_id,
                        result,
                    )
                    return

        self.coordinator.mark_pv_linkage_draft_applied()
        if accepted_configuration:
            self.hass.async_create_task(
                async_confirm_configuration(self.hass, charge_point)
            )
