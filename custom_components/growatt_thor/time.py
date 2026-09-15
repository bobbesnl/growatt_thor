"""Time entities for Growatt THOR configuration."""
from __future__ import annotations

import logging
from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

from ocpp.v16.enums import ConfigurationStatus

from .action_errors import raise_charger_disconnected, raise_write_blocked
from .const import DOMAIN
from .configuration_writes import ConfigurationWriteStatus
from .charging_controls import (
    ChargingControl,
    control_is_applicable,
    control_write_block_reason,
)
from .pv_linkage import PvBoostMode
from .write_queue import (
    ChargerConnectionUnavailable,
    ChargerRequestOutcomeUncertain,
    ChargerWriteResult,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Growatt THOR time entities."""
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities([
        AutoChargeStartTime(coordinator, entry),
        AutoChargeStopTime(coordinator, entry),
        PvManualBoostStartTime(coordinator, entry),
        PvManualBoostEndTime(coordinator, entry),
        PvSmartBoostFinishTime(coordinator, entry),
    ])


class BaseAutoChargeTime(CoordinatorEntity, TimeEntity):
    """Base class for auto charge time entities (auto-apply via queue)."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:clock-outline"

    _CONFIG_KEY = "G_AutoChargeTime"

    def __init__(self, coordinator, entry, key):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }
        self.hass = coordinator.hass

    @property
    def available(self):
        # Writing a schedule while charging is unsafe, but that temporary write
        # guard must not hide the already reported schedule from Home Assistant.
        return (
            super().available
            and self.coordinator.connected
            and control_is_applicable(
                ChargingControl.AUTO_CHARGE_SCHEDULE,
                self.coordinator.configuration_values,
            )
            and self.native_value is not None
        )

    @property
    def _write_block_reason(self) -> str | None:
        return control_write_block_reason(
            ChargingControl.AUTO_CHARGE_SCHEDULE,
            self.coordinator.configuration_values,
            connected=self.coordinator.connected,
            transaction_active=self.coordinator.transaction_is_active,
            charger_faulted=self.coordinator.charger_is_faulted,
        )

    async def async_set_value(self, value: time) -> None:
        """Update time and auto-apply schedule via write queue."""
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning("Cannot change %s: %s", self.name, block_reason)
            raise_write_blocked(block_reason)
        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if not charge_point:
            _LOGGER.warning("Cannot change %s: charger not connected", self.name)
            raise_charger_disconnected()

        _LOGGER.info("📝 %s changed to %s (auto-queuing)", self.name, value.strftime("%H:%M"))

        # Update pending value in coordinator
        if self._is_start:
            self.coordinator.auto_charge_start_time_pending = value
        else:
            self.coordinator.auto_charge_stop_time_pending = value

        self.coordinator.async_set_updated_data(True)

        # Auto-apply via queue when both are set
        start_time = self.coordinator.auto_charge_start_time_pending
        stop_time = self.coordinator.auto_charge_stop_time_pending

        if start_time and stop_time:
            formatted_value = f"{start_time.strftime('%H:%M')}-{stop_time.strftime('%H:%M')}"
            _LOGGER.info("🔄 Auto-queueing schedule update: %s", formatted_value)

            self.coordinator.begin_configuration_write(
                self._CONFIG_KEY,
                formatted_value,
            )
            await self.coordinator.queue_write(
                self._apply_schedule,
                charge_point,
                formatted_value,
                start_time,
                stop_time,
                dedupe_key=self._CONFIG_KEY,  # ✅ only keep latest G_AutoChargeTime in queue
                command_name=f"ChangeConfiguration({self._CONFIG_KEY})",
                requires_connection=True,
                configuration_key=self._CONFIG_KEY,
            )

    async def _apply_schedule(
        self,
        charge_point,
        formatted_value: str,
        start_time: time,
        stop_time: time,
    ) -> ChargerWriteResult:
        """Actually write schedule to the charger (runs inside write-queue)."""
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning(
                "Skipping queued charging schedule change: %s",
                block_reason,
            )
            self.coordinator.mark_configuration_write(
                self._CONFIG_KEY,
                ConfigurationWriteStatus.SKIPPED,
                result=block_reason,
            )
            return ChargerWriteResult.skipped(block_reason)
        try:
            result = await charge_point.change_configuration(
                self._CONFIG_KEY,
                formatted_value
            )

            accepted = result in {
                ConfigurationStatus.accepted,
                ConfigurationStatus.reboot_required,
            }
            self.coordinator.acknowledge_configuration_write(
                self._CONFIG_KEY,
                accepted=accepted,
                result=result,
            )
            if accepted:
                self.coordinator.update_configuration_value(
                    self._CONFIG_KEY,
                    formatted_value,
                )
                self.coordinator.schedule_configuration_refresh()

            if result == ConfigurationStatus.accepted:
                self.coordinator.auto_charge_start_time = start_time
                self.coordinator.auto_charge_stop_time = stop_time
                self.coordinator.async_set_updated_data(True)
                _LOGGER.info("✅ Auto-applied charging schedule: %s", formatted_value)
            elif result == ConfigurationStatus.reboot_required:
                self.coordinator.auto_charge_start_time = start_time
                self.coordinator.auto_charge_stop_time = stop_time
                self.coordinator.async_set_updated_data(True)
                _LOGGER.warning("⚠️ Charging schedule applied (reboot required): %s", formatted_value)
            else:
                _LOGGER.error("❌ Charging schedule rejected: %s", result)
                return ChargerWriteResult.failed("charger_rejected", result)

            return ChargerWriteResult.success(result)

        except ChargerConnectionUnavailable:
            raise
        except ChargerRequestOutcomeUncertain as exc:
            self.coordinator.mark_configuration_write(
                self._CONFIG_KEY,
                ConfigurationWriteStatus.UNCERTAIN,
                result=str(exc),
            )
            self.coordinator.schedule_configuration_refresh(delay=0)
            return ChargerWriteResult.uncertain(str(exc))
        except Exception as exc:
            _LOGGER.error("❌ Failed to auto-apply schedule: %s", exc, exc_info=True)
            return ChargerWriteResult.failed("unexpected_error")


class AutoChargeStartTime(BaseAutoChargeTime):
    """Auto charge start time configuration."""

    _attr_translation_key = "auto_charge_start_time"
    _is_start = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "auto_charge_start_time")

    @property
    def native_value(self):
        """Return pending start time."""
        return self.coordinator.auto_charge_start_time_pending

    @property
    def extra_state_attributes(self):
        """Show Thor value vs pending."""
        thor_value = self.coordinator.auto_charge_start_time
        return {
            "thor_value": thor_value.strftime("%H:%M") if thor_value else None,
            "note": "Auto-applies via write queue",
        }


class AutoChargeStopTime(BaseAutoChargeTime):
    """Auto charge stop time configuration."""

    _attr_translation_key = "auto_charge_stop_time"
    _is_start = False

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "auto_charge_stop_time")

    @property
    def native_value(self):
        """Return pending stop time."""
        return self.coordinator.auto_charge_stop_time_pending

    @property
    def extra_state_attributes(self):
        """Show Thor value vs pending."""
        thor_value = self.coordinator.auto_charge_stop_time
        return {
            "thor_value": thor_value.strftime("%H:%M") if thor_value else None,
            "note": "Auto-applies via write queue",
        }


class BasePvBoostTime(CoordinatorEntity, TimeEntity):
    """Edit one local PV Boost draft time."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:clock-outline"
    _required_mode: PvBoostMode
    _coordinator_field: str

    def __init__(self, coordinator, entry, key):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}_draft"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }

    @property
    def native_value(self):
        return getattr(self.coordinator, self._coordinator_field)

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
    def available(self):
        # Temporary write guards belong in async_set_value, not availability.
        # The locally edited draft remains useful state during a charge session.
        return (
            super().available
            and self.coordinator.connected
            and control_is_applicable(
                ChargingControl.SOLAR_BOOST,
                self.coordinator.configuration_values,
            )
            and self.coordinator.pv_boost_mode_draft == self._required_mode
            and self.native_value is not None
        )

    @property
    def extra_state_attributes(self):
        return {"information": "details"}

    async def async_set_value(self, value: time) -> None:
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning("Cannot edit PV Boost time: %s", block_reason)
            raise_write_blocked(block_reason)
        self.coordinator.update_pv_linkage_draft(
            **{self._coordinator_field: value}
        )


class PvManualBoostStartTime(BasePvBoostTime):
    """Edit the Manual Boost start time."""

    _attr_translation_key = "pv_manual_boost_start"
    _required_mode = PvBoostMode.MANUAL
    _coordinator_field = "pv_manual_start_draft"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "pv_manual_boost_start")


class PvManualBoostEndTime(BasePvBoostTime):
    """Edit the Manual Boost end time."""

    _attr_translation_key = "pv_manual_boost_end"
    _required_mode = PvBoostMode.MANUAL
    _coordinator_field = "pv_manual_end_draft"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "pv_manual_boost_end")


class PvSmartBoostFinishTime(BasePvBoostTime):
    """Edit the Smart Boost charging finish time."""

    _attr_translation_key = "pv_smart_boost_finish"
    _required_mode = PvBoostMode.SMART
    _coordinator_field = "pv_smart_finish_draft"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "pv_smart_boost_finish")
