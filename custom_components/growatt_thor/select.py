"""Select entities for verified Growatt THOR charging controls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import GrowattCoordinator
    from .runtime.entry import ThorConfigEntry

import asyncio
import logging

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory

from .charging.control_capabilities import (
    PV_LINKAGE_WORKING_MODES,
    ChargingControl,
    available_working_mode_options,
    control_is_applicable,
    encode_control_value,
    encode_working_mode,
    selected_working_mode,
)
from .charging.pv_linkage import PvBoostMode
from .configuration.controls import ConfigurationControl
from .configuration.values import (
    CONFIGURATION_ENTITY_OPTIONS,
    ConfigurationScalar,
)
from .configuration.writer import ConfigurationWrite, ConfigurationWriter, WritePolicy
from .const import CONFIGURATION_WRITE_SPACING_SECONDS
from .entity import ThorEntity
from .runtime.action_errors import (
    raise_action_validation,
    raise_write_blocked,
)
from .runtime.write_results import (
    ChargerWriteResult,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ThorConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Growatt THOR select entities."""
    # HA forwards platforms only after this entry has claimed its coordinator.
    coordinator = cast("GrowattCoordinator", entry.runtime_data.coordinator)
    async_add_entities(
        [
            WorkingModeSelect(coordinator, entry),
            *(
                ConfigurationControlSelect(coordinator, entry, description)
                for description in CONTROL_SELECTS
            ),
            PvBoostDraftSelect(coordinator, entry),
        ]
    )


class WorkingModeWritePolicy(WritePolicy[str]):
    """Write one working mode through the key its encoding selects.

    Working modes use different underlying Growatt keys. The entity intent
    token, carried as the rollback token ``(option, intent)``, therefore
    complements the per-key generation and prevents an older mode response
    from winning across keys.
    """

    label = "working mode"
    dedupe_key = "working_mode"

    def __init__(self, entity: WorkingModeSelect) -> None:
        super().__init__(entity.coordinator)
        self.entity = entity
        self.coordinator = entity.coordinator

    @staticmethod
    def _selection(write: ConfigurationWrite[str]) -> tuple[str, int]:
        return cast(tuple[str, int], write.previous)

    def encode(self, value: str) -> tuple[str, str]:
        return encode_working_mode(value)

    def request_block_reason(self) -> str | None:
        return self.coordinator.write_block_reason(ChargingControl.WORKING_MODE)

    def queued_block_reason(self, write: ConfigurationWrite[str]) -> str | None:
        if (
            write.value in PV_LINKAGE_WORKING_MODES
            and not self.coordinator.external_meter.ready_for_pv
        ):
            return "external_meter_not_ready"
        return self.request_block_reason()

    def apply_optimistic(self, value: str) -> object:
        entity = self.entity
        entity._intent_sequence += 1
        intent = entity._intent_sequence
        entity._pending_option = value
        entity._pending_intent = intent
        if entity._readback_task is not None and not entity._readback_task.done():
            entity._readback_task.cancel()
        entity.async_write_ha_state()
        return (value, intent)

    def on_skipped(self, write: ConfigurationWrite[str], reason: str) -> None:
        if reason == "external_meter_not_ready":
            _LOGGER.warning(
                "Skipping queued PV Linkage change: external meter health is %s",
                self.coordinator.external_meter.health,
            )
        else:
            _LOGGER.warning("Skipping queued working mode change: %s", reason)
        self.entity._clear_pending_option(*self._selection(write))

    def on_unsent(self, write: ConfigurationWrite[str]) -> None:
        # The entity intent, not a per-key generation, owns cross-key selection.
        self.entity._clear_pending_option(*self._selection(write))

    def on_rejected(self, write: ConfigurationWrite[str], result: object) -> None:
        _LOGGER.error("Working mode change rejected by charger: %s", result)
        self.entity._clear_pending_option(*self._selection(write))

    def on_unexpected(
        self, write: ConfigurationWrite[str], exc: Exception
    ) -> ChargerWriteResult | None:
        # Clear this intent's pending selection before the queue classifies the failure.
        self.entity._clear_pending_option(*self._selection(write))
        return None

    def apply_accepted(self, write: ConfigurationWrite[str]) -> None:
        if not self.entity._selection_is_current(*self._selection(write)):
            return
        option = write.value
        super().apply_accepted(write)
        reported_mode = {
            "fast": "Fast",
            "pv_linkage": "PVlink",
            "pv_linkage_plus": "PVlink",
            "off_peak": "Off Peak",
        }[option]
        self.coordinator.update_configuration_value(
            "G_WorkingMode",
            reported_mode,
        )
        if option == "off_peak":
            self.coordinator.update_configuration_value("G_SolarMode", "1&0")
        elif option in {"fast", "pv_linkage", "pv_linkage_plus"}:
            self.coordinator.update_configuration_value(
                "G_OffPeakEnable",
                "1&Disable",
            )

    def schedule_readback(self, write: ConfigurationWrite[str], *, delay: float | None) -> None:
        option, intent = self._selection(write)
        if not self.entity._selection_is_current(option, intent):
            # Even a superseded accepted write changed the charger briefly;
            # the shared refresh waits for the replacement before reading back.
            super().schedule_readback(write, delay=delay)
            return
        refresh = (
            self.entity._refresh_configuration(option, intent)
            if delay is None
            else self.entity._refresh_configuration(option, intent, delay=delay)
        )
        self.entity._readback_task = self.entity.hass.async_create_task(refresh)

    def report_accepted(self, write: ConfigurationWrite[str], result: object) -> None:
        """Working mode changes log only rejections."""


class WorkingModeSelect(ThorEntity, SelectEntity):
    """Select a charging strategy through the captured indirect writes."""

    coordinator: GrowattCoordinator

    _attr_has_entity_name = True
    _attr_translation_key = "working_mode"
    _attr_icon = "mdi:ev-station"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: GrowattCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._pending_option: str | None = None
        self._intent_sequence = 0
        self._pending_intent: int | None = None
        self._readback_task: asyncio.Task[None] | None = None
        self._attr_unique_id = f"{entry.entry_id}_working_mode_control"
        self._writer = ConfigurationWriter(coordinator, WorkingModeWritePolicy(self))

    @property
    def current_option(self) -> str | None:
        if self._pending_option is not None:
            return self._pending_option
        return selected_working_mode(self.coordinator.configuration_values)

    @property
    def options(self) -> list[str]:
        return available_working_mode_options(
            self.current_option,
            external_meter_ready=self.coordinator.external_meter.ready_for_pv,
        )

    @property
    def available(self) -> bool:
        # An active charging transaction prevents mode changes, but the last
        # reported strategy remains useful state and must stay visible.
        return super().available and self.coordinator.connected and self.current_option is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.information_attributes

    async def async_select_option(self, option: str) -> None:
        if option == self.current_option:
            return
        if option not in self.options:
            _LOGGER.warning(
                "Cannot select PV Linkage while external meter health is %s",
                self.coordinator.external_meter.health,
            )
            raise_action_validation(
                (
                    "external_meter_not_ready"
                    if option in PV_LINKAGE_WORKING_MODES
                    else "invalid_working_mode"
                ),
                placeholders={"option": option},
            )
        await self._writer.async_request(option)

    def _selection_is_current(self, option: str, intent: int) -> bool:
        """Return whether a callback owns the latest logical mode selection."""
        return self._pending_option == option and self._pending_intent == intent

    def _clear_pending_option(self, option: str, intent: int) -> None:
        """Clear only the pending selection owned by this write."""
        if self._selection_is_current(option, intent):
            self._pending_option = None
            self._pending_intent = None
            self.async_write_ha_state()

    async def _refresh_configuration(
        self,
        option: str,
        intent: int,
        *,
        delay: float = CONFIGURATION_WRITE_SPACING_SECONDS,
    ) -> None:
        """Confirm the effective mode through the shared, coalesced readback."""
        try:
            refresh_task = self.coordinator.schedule_configuration_refresh(delay=delay)
            # This entity owns only its waiter.  Shielding keeps cancellation
            # (for a newer selection or entity removal) from cancelling the
            # readback shared by all configuration entities.
            await asyncio.shield(refresh_task)
        except asyncio.CancelledError:
            return
        finally:
            self._clear_pending_option(option, intent)

    async def async_will_remove_from_hass(self) -> None:
        """Cancel a delayed mode readback when the entity is removed."""
        self._pending_option = None
        self._pending_intent = None
        if self._readback_task is not None and not self._readback_task.done():
            self._readback_task.cancel()
        await super().async_will_remove_from_hass()


@dataclass(frozen=True, kw_only=True)
class ConfigurationControlSelectDescription:
    """Declare one verified option control; the unique ID is ``<entry>_<key>_control``."""

    key: str
    control: ChargingControl
    icon: str
    device: Literal["charger", "meter"] = "charger"


CONTROL_SELECTS = (
    # Explicit, idle-only authorization changes; never issue a reboot or start.
    ConfigurationControlSelectDescription(
        key="authorization_mode",
        control=ChargingControl.AUTHORIZATION_MODE,
        icon="mdi:card-account-details-outline",
    ),
    # Select the captured external current sampling method.
    ConfigurationControlSelectDescription(
        key="external_sampling_method",
        control=ChargingControl.EXTERNAL_SAMPLING_METHOD,
        icon="mdi:connection",
        device="meter",
    ),
    # Select the Modbus meter model reported through OCPP.
    ConfigurationControlSelectDescription(
        key="power_meter_type",
        control=ChargingControl.POWER_METER_TYPE,
        icon="mdi:counter",
        device="meter",
    ),
)


class ConfigurationControlSelect(ThorEntity, SelectEntity):
    """Write one verified Growatt option control."""

    coordinator: GrowattCoordinator

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: GrowattCoordinator,
        entry: ConfigEntry,
        description: ConfigurationControlSelectDescription,
    ) -> None:
        super().__init__(coordinator, entry, device=description.device)
        self._description = description
        self._configuration = ConfigurationControl(coordinator, description.control)
        self._attr_unique_id = f"{entry.entry_id}_{description.key}_control"
        self._attr_translation_key = description.key
        self._attr_icon = description.icon
        self._attr_options = list(CONFIGURATION_ENTITY_OPTIONS[self._configuration.key])

    @property
    def current_option(self) -> ConfigurationScalar:
        return self._configuration.state

    @property
    def available(self) -> bool:
        return (
            super().available and self._configuration.available and self.current_option is not None
        )

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return self._configuration.attributes

    async def async_select_option(self, option: str) -> None:
        await self._configuration.async_write(
            encode_control_value(self._description.control, option)
        )


class PvBoostDraftSelect(ThorEntity, SelectEntity):
    """Edit the local PV Boost mode without immediately writing the charger."""

    _attr_has_entity_name = True
    _attr_translation_key = "pv_boost_mode"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:rocket-launch-outline"
    _attr_options = [mode.value for mode in PvBoostMode]

    def __init__(self, coordinator: GrowattCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_pv_boost_mode_draft"

    @property
    def current_option(self) -> ConfigurationScalar:
        mode = self.coordinator.pv_draft.boost_mode
        return mode.value if mode is not None else None

    @property
    def _write_block_reason(self) -> str | None:
        return self.coordinator.write_block_reason(ChargingControl.SOLAR_BOOST)

    @property
    def available(self) -> bool:
        # Draft state is still meaningful during charging or a charger fault.
        # Those conditions block applying it, but should not make it disappear.
        return (
            super().available
            and self.coordinator.connected
            and control_is_applicable(
                ChargingControl.SOLAR_BOOST,
                self.coordinator.configuration_values,
            )
            and self.current_option is not None
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.information_attributes

    async def async_select_option(self, option: str) -> None:
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning("Cannot edit PV Boost mode: %s", block_reason)
            raise_write_blocked(block_reason)
        self.coordinator.update_pv_linkage_draft(boost_mode=PvBoostMode(option))
