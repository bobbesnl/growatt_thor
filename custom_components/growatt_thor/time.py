"""Time entities for Growatt THOR configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .runtime.keys import ACTIVE_CHARGE_POINT

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .runtime.entry import ThorConfigEntry

import logging
from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.helpers.entity import EntityCategory
from ocpp.v16.enums import ConfigurationStatus

from .charging.control_capabilities import (
    ChargingControl,
    control_is_applicable,
)
from .charging.pv_linkage import PvBoostMode
from .configuration.controls import GrowattConfigurationWriteMixin
from .configuration.writes import ConfigurationWriteStatus
from .entity import ThorEntity
from .runtime.action_errors import raise_charger_disconnected, raise_write_blocked
from .runtime.write_results import (
    CONFIGURATION_WRITE_POLICY,
    ChargerConnectionUnavailable,
    ChargerRequestOutcomeUncertain,
    ChargerWriteResult,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ThorConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Growatt THOR time entities."""
    coordinator = entry.runtime_data.coordinator

    async_add_entities(
        [
            AutoChargeStartTime(coordinator, entry),
            AutoChargeStopTime(coordinator, entry),
            PvManualBoostStartTime(coordinator, entry),
            PvManualBoostEndTime(coordinator, entry),
            PvSmartBoostFinishTime(coordinator, entry),
        ]
    )


class BaseAutoChargeTime(GrowattConfigurationWriteMixin, ThorEntity, TimeEntity):
    """Base class for auto charge time entities (auto-apply via queue)."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:clock-outline"

    _CONFIG_KEY = "G_AutoChargeTime"

    def __init__(self, coordinator, entry, key):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{key}"

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
        return self.coordinator.write_block_reason(ChargingControl.AUTO_CHARGE_SCHEDULE)

    def _encode(self, value) -> str:
        start_time, stop_time = value
        return f"{start_time.strftime('%H:%M')}-{stop_time.strftime('%H:%M')}"

    def _restore_reported_schedule(self, generation: int) -> None:
        self._restore_optimistic(generation)

    def _restore_optimistic(self, generation: int, *, previous=None) -> None:
        """Discard an unsent optimistic schedule owned by this generation."""
        if not self.coordinator.configuration_write_is_current(
            self._CONFIG_KEY,
            generation,
        ):
            return
        self.coordinator.auto_charge_start_time_pending = self.coordinator.auto_charge_start_time
        self.coordinator.auto_charge_stop_time_pending = self.coordinator.auto_charge_stop_time
        self.coordinator.async_set_updated_data(True)

    async def async_set_value(self, value: time) -> None:
        """Update time and auto-apply schedule via write queue."""
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning("Cannot change %s: %s", self.name, block_reason)
            raise_write_blocked(block_reason)
        charge_point = self.coordinator.runtime_data.get(ACTIVE_CHARGE_POINT)
        if not charge_point:
            _LOGGER.warning("Cannot change %s: charger not connected", self.name)
            raise_charger_disconnected()

        _LOGGER.info("%s changed to %s (auto-queuing)", self.name, value.strftime("%H:%M"))

        # Update pending value in coordinator
        if self._is_start:
            self.coordinator.auto_charge_start_time_pending = value
        else:
            self.coordinator.auto_charge_stop_time_pending = value

        self.coordinator.async_set_updated_data(True)

        # The two HA time entities represent one THOR configuration value.  A
        # short shared debounce gives back-to-back automation calls time to
        # update both pending fields before one final payload is constructed.
        start_time = self.coordinator.auto_charge_start_time_pending
        stop_time = self.coordinator.auto_charge_stop_time_pending

        if start_time and stop_time:
            _LOGGER.info("Debouncing paired Auto Charge schedule update")
            self.coordinator.schedule_auto_charge_schedule_write(
                lambda: self._queue_pending_schedule(charge_point)
            )

    async def _queue_pending_schedule(self, charge_point) -> None:
        """Queue one snapshot after the paired entity values have settled."""
        start_time = self.coordinator.auto_charge_start_time_pending
        stop_time = self.coordinator.auto_charge_stop_time_pending
        if start_time is None or stop_time is None:
            return

        formatted_value = self._encode((start_time, stop_time))
        _LOGGER.info("Auto-queueing schedule update: %s", formatted_value)

        generation = self.coordinator.begin_configuration_write(
            self._CONFIG_KEY,
            formatted_value,
        )
        # The originating HA calls have already returned before this debounce
        # callback runs, so there is no caller left to receive a completion
        # exception.  The queue still publishes its terminal Command ID and
        # result through the shared Last command result sensor.
        await self.coordinator.queue_write(
            self._apply_schedule,
            charge_point,
            formatted_value,
            start_time,
            stop_time,
            generation,
            dedupe_key=self._CONFIG_KEY,
            command_name=f"ChangeConfiguration({self._CONFIG_KEY})",
            requires_connection=True,
            configuration_key=self._CONFIG_KEY,
            configuration_generation=generation,
            policy=CONFIGURATION_WRITE_POLICY,
            on_unsent=lambda _result: self._restore_reported_schedule(generation),
        )

    async def _apply_schedule(
        self,
        charge_point,
        formatted_value: str,
        start_time: time,
        stop_time: time,
        generation: int,
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
                generation=generation,
                result=block_reason,
            )
            return ChargerWriteResult.skipped(block_reason)
        try:
            response = await self._configuration_exchange(
                charge_point, self._CONFIG_KEY, formatted_value, generation
            )
            result, accepted, outcome_is_current = (
                response.result,
                response.accepted,
                response.current,
            )
            if accepted and outcome_is_current:
                self._on_accepted(formatted_value, key=self._CONFIG_KEY)
            if accepted:
                self.coordinator.schedule_configuration_refresh()

            if result == ConfigurationStatus.accepted:
                if outcome_is_current:
                    self.coordinator.auto_charge_start_time = start_time
                    self.coordinator.auto_charge_stop_time = stop_time
                    self.coordinator.async_set_updated_data(True)
                _LOGGER.info("Auto-applied charging schedule: %s", formatted_value)
            elif result == ConfigurationStatus.reboot_required:
                if outcome_is_current:
                    self.coordinator.auto_charge_start_time = start_time
                    self.coordinator.auto_charge_stop_time = stop_time
                    self.coordinator.async_set_updated_data(True)
                _LOGGER.warning("Charging schedule applied (reboot required): %s", formatted_value)
            else:
                _LOGGER.error("Charging schedule rejected: %s", result)
                return ChargerWriteResult.failed("charger_rejected", result)

            return ChargerWriteResult.success(result)

        except ChargerConnectionUnavailable:
            raise
        except ChargerRequestOutcomeUncertain as exc:
            self.coordinator.mark_configuration_write(
                self._CONFIG_KEY,
                ConfigurationWriteStatus.UNCERTAIN,
                generation=generation,
                result=str(exc),
            )
            self.coordinator.schedule_configuration_refresh(delay=0)
            return ChargerWriteResult.uncertain(str(exc))
        except Exception as exc:
            _LOGGER.error("Failed to auto-apply schedule: %s", exc, exc_info=True)
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


class BasePvBoostTime(ThorEntity, TimeEntity):
    """Edit one local PV Boost draft time."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:clock-outline"
    _required_mode: PvBoostMode
    _coordinator_field: str

    def __init__(self, coordinator, entry, key):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{key}_draft"

    @property
    def native_value(self):
        return getattr(self.coordinator, self._coordinator_field)

    @property
    def _write_block_reason(self) -> str | None:
        return self.coordinator.write_block_reason(ChargingControl.SOLAR_BOOST)

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
        return self.information_attributes

    async def async_set_value(self, value: time) -> None:
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning("Cannot edit PV Boost time: %s", block_reason)
            raise_write_blocked(block_reason)
        self.coordinator.update_pv_linkage_draft(**{self._coordinator_field: value})


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
