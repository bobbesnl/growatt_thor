"""Button entities for Growatt THOR configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .runtime.keys import ACTIVE_CHARGE_POINT

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .runtime.entry import ThorConfigEntry

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import dt as dt_util

from .charging.commands import DEFAULT_ID_TAG as DEFAULT_ID_TAG
from .charging.commands import StartChargingCommand, StopChargingCommand
from .charging.control_capabilities import (
    ChargingControl,
)
from .charging.pv_apply import apply_pv_linkage_writes
from .charging.pv_linkage import (
    build_pv_linkage_writes,
    draft_validation_errors,
)
from .entity import ThorEntity
from .runtime.action_errors import (
    async_require_command_completion,
    raise_action_validation,
    raise_charger_disconnected,
    raise_write_blocked,
)
from .runtime.write_results import (
    CONFIGURATION_WRITE_POLICY,
    ChargerWriteResult,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ThorConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Growatt THOR button entities."""
    coordinator = entry.runtime_data.coordinator

    async_add_entities(
        [
            StartChargingButton(coordinator, entry),
            StopChargingButton(coordinator, entry),
            ApplyPvLinkageButton(coordinator, entry),
        ]
    )


# Start Charging Button


class StartChargingButton(ThorEntity, ButtonEntity):
    """Expose Start while the command boundary owns validation and execution."""

    _attr_translation_key = "start_charging"
    _attr_icon = "mdi:play-circle"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_start_charging"

    @property
    def _write_block_reason(self) -> str | None:
        return StartChargingCommand(self.coordinator).write_block_reason

    @property
    def available(self) -> bool:
        return super().available and self._write_block_reason is None

    async def async_press(self) -> None:
        await StartChargingCommand(self.coordinator).async_request()


# Stop Charging Button


class StopChargingButton(ThorEntity, ButtonEntity):
    """Button to stop a charging session."""

    _attr_has_entity_name = True
    _attr_translation_key = "stop_charging"
    _attr_icon = "mdi:stop-circle"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_stop_charging"

    async def async_press(self) -> None:
        """Delegate the entity action to the common command boundary."""
        await StopChargingCommand(self.coordinator).async_request()


class ApplyPvLinkageButton(ThorEntity, ButtonEntity):
    """Apply the complete local PV Linkage boost draft."""

    _attr_has_entity_name = True
    _attr_translation_key = "apply_pv_linkage"
    _attr_icon = "mdi:check-bold"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_apply_pv_linkage"

    @property
    def _write_block_reason(self) -> str | None:
        return self.coordinator.write_block_reason(ChargingControl.SOLAR_BOOST)

    @property
    def _validation_errors(self) -> tuple[str, ...]:
        draft = self.coordinator.pv_linkage_draft()
        return ("draft_not_initialized",) if draft is None else draft_validation_errors(draft)

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
            **self.information_attributes,
            "pending_changes": self.coordinator.pv_linkage_draft_dirty,
            "validation_errors": list(self._validation_errors),
            "last_apply": (last_apply.as_dict() if last_apply is not None else None),
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
                        errors if draft is not None else ("draft_not_initialized",)
                    ),
                },
            )

        charge_point = self.coordinator.runtime_data.get(ACTIVE_CHARGE_POINT)
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
