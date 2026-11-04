"""Time entities for Growatt THOR configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .configuration.contracts import ConfigurationTransport
    from .coordinator import GrowattCoordinator
    from .runtime.entry import ThorConfigEntry

import logging
from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
from ocpp.v16.enums import ConfigurationStatus

from .charging.control_capabilities import (
    ChargingControl,
    control_is_applicable,
)
from .charging.pv_linkage import PvBoostMode
from .configuration.writer import ConfigurationWrite, ConfigurationWriter, WritePolicy
from .entity import ThorEntity
from .runtime.action_errors import raise_write_blocked
from .runtime.write_results import (
    ChargerWriteResult,
)

_LOGGER = logging.getLogger(__name__)

AUTO_CHARGE_TIME_KEY = "G_AutoChargeTime"


async def async_setup_entry(
    hass: HomeAssistant, entry: ThorConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Growatt THOR time entities."""
    # HA forwards platforms only after this entry has claimed its coordinator.
    coordinator = cast("GrowattCoordinator", entry.runtime_data.coordinator)

    async_add_entities(
        [
            AutoChargeStartTime(coordinator, entry),
            AutoChargeStopTime(coordinator, entry),
            PvManualBoostStartTime(coordinator, entry),
            PvManualBoostEndTime(coordinator, entry),
            PvSmartBoostFinishTime(coordinator, entry),
        ]
    )


AutoChargeSchedule = tuple[time, time]


class AutoChargeScheduleWritePolicy(WritePolicy[AutoChargeSchedule]):
    """Write the paired start and stop times as one G_AutoChargeTime value.

    Pending fields are restored only for an unsent write that still owns the
    newest generation; rejection and unexpected execution failure do not roll
    back.
    """

    # Return the existing terminal failure for unexpected schedule-write
    # errors, including those after the acknowledgement.
    guards_outcome = True
    refreshes_on_apply = True

    def __init__(self, entity: BaseAutoChargeTime) -> None:
        super().__init__(entity.coordinator)
        self.entity = entity
        self.coordinator = entity.coordinator

    @property
    def label(self) -> str:
        return str(self.entity.name)

    def encode(self, value: AutoChargeSchedule) -> tuple[str, str]:
        start_time, stop_time = value
        return AUTO_CHARGE_TIME_KEY, (
            f"{start_time.strftime('%H:%M')}-{stop_time.strftime('%H:%M')}"
        )

    def request_block_reason(self) -> str | None:
        return self.coordinator.write_block_reason(ChargingControl.AUTO_CHARGE_SCHEDULE)

    def on_skipped(self, write: ConfigurationWrite[AutoChargeSchedule], reason: str) -> None:
        _LOGGER.warning("Skipping queued charging schedule change: %s", reason)

    def on_unsent(self, write: ConfigurationWrite[AutoChargeSchedule]) -> None:
        """Discard an unsent optimistic schedule owned by this generation."""
        if not self.coordinator.configuration_write_is_current(write.key, write.generation):
            return
        self.coordinator.auto_charge_start_time_pending = self.coordinator.auto_charge_start_time
        self.coordinator.auto_charge_stop_time_pending = self.coordinator.auto_charge_stop_time
        self.coordinator.async_set_updated_data(True)

    def apply_accepted(self, write: ConfigurationWrite[AutoChargeSchedule]) -> None:
        super().apply_accepted(write)
        self.coordinator.schedule_configuration_refresh()
        self.coordinator.auto_charge_start_time, self.coordinator.auto_charge_stop_time = (
            write.value
        )
        self.coordinator.async_set_updated_data(True)

    def report_accepted(
        self, write: ConfigurationWrite[AutoChargeSchedule], result: object
    ) -> None:
        if result == ConfigurationStatus.reboot_required:
            _LOGGER.warning("Charging schedule applied (reboot required): %s", write.raw_value)
        else:
            _LOGGER.info("Auto-applied charging schedule: %s", write.raw_value)

    def on_rejected(self, write: ConfigurationWrite[AutoChargeSchedule], result: object) -> None:
        _LOGGER.error("Charging schedule rejected: %s", result)

    def on_unexpected(
        self, write: ConfigurationWrite[AutoChargeSchedule], exc: Exception
    ) -> ChargerWriteResult | None:
        _LOGGER.error("Failed to auto-apply schedule: %s", exc, exc_info=True)
        return ChargerWriteResult.failed("unexpected_error")


class BaseAutoChargeTime(ThorEntity, TimeEntity):
    """Base class for auto charge time entities (auto-apply via queue)."""

    coordinator: GrowattCoordinator

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:clock-outline"

    _is_start: bool

    def __init__(self, coordinator: GrowattCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._writer = ConfigurationWriter(coordinator, AutoChargeScheduleWritePolicy(self))

    @property
    def available(self) -> bool:
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

    async def async_set_value(self, value: time) -> None:
        """Update time and auto-apply schedule via write queue."""
        charge_point = self._writer.require_charge_point()

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

    async def _queue_pending_schedule(self, charge_point: ConfigurationTransport) -> None:
        """Queue one snapshot after the paired entity values have settled."""
        start_time = self.coordinator.auto_charge_start_time_pending
        stop_time = self.coordinator.auto_charge_stop_time_pending
        if start_time is None or stop_time is None:
            return

        _LOGGER.info(
            "Auto-queueing schedule update: %s-%s",
            start_time.strftime("%H:%M"),
            stop_time.strftime("%H:%M"),
        )
        # The originating HA calls have already returned before this debounce
        # callback runs, so there is no caller left to receive a completion
        # exception.  The queue still publishes its terminal Command ID and
        # result through the shared Last command result sensor.
        await self._writer.async_enqueue(charge_point, (start_time, stop_time))


class AutoChargeStartTime(BaseAutoChargeTime):
    """Auto charge start time configuration."""

    _attr_translation_key = "auto_charge_start_time"
    _is_start = True

    def __init__(self, coordinator: GrowattCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "auto_charge_start_time")

    @property
    def native_value(self) -> time | None:
        """Return pending start time."""
        return self.coordinator.auto_charge_start_time_pending

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
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

    def __init__(self, coordinator: GrowattCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "auto_charge_stop_time")

    @property
    def native_value(self) -> time | None:
        """Return pending stop time."""
        return self.coordinator.auto_charge_stop_time_pending

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
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
    _draft_field: str

    def __init__(self, coordinator: GrowattCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{key}_draft"

    @property
    def native_value(self) -> time | None:
        return cast(time | None, getattr(self.coordinator.pv_draft, self._draft_field))

    @property
    def _write_block_reason(self) -> str | None:
        return self.coordinator.write_block_reason(ChargingControl.SOLAR_BOOST)

    @property
    def available(self) -> bool:
        # Temporary write guards belong in async_set_value, not availability.
        # The locally edited draft remains useful state during a charge session.
        return (
            super().available
            and self.coordinator.connected
            and control_is_applicable(
                ChargingControl.SOLAR_BOOST,
                self.coordinator.configuration_values,
            )
            and self.coordinator.pv_draft.boost_mode == self._required_mode
            and self.native_value is not None
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.information_attributes

    async def async_set_value(self, value: time) -> None:
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning("Cannot edit PV Boost time: %s", block_reason)
            raise_write_blocked(block_reason)
        self.coordinator.update_pv_linkage_draft(**{self._draft_field: value})


class PvManualBoostStartTime(BasePvBoostTime):
    """Edit the Manual Boost start time."""

    _attr_translation_key = "pv_manual_boost_start"
    _required_mode = PvBoostMode.MANUAL
    _draft_field = "manual_start"

    def __init__(self, coordinator: GrowattCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "pv_manual_boost_start")


class PvManualBoostEndTime(BasePvBoostTime):
    """Edit the Manual Boost end time."""

    _attr_translation_key = "pv_manual_boost_end"
    _required_mode = PvBoostMode.MANUAL
    _draft_field = "manual_end"

    def __init__(self, coordinator: GrowattCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "pv_manual_boost_end")


class PvSmartBoostFinishTime(BasePvBoostTime):
    """Edit the Smart Boost charging finish time."""

    _attr_translation_key = "pv_smart_boost_finish"
    _required_mode = PvBoostMode.SMART
    _draft_field = "smart_finish"

    def __init__(self, coordinator: GrowattCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "pv_smart_boost_finish")
