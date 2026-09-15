"""Select entities for verified Growatt THOR charging controls."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from ocpp.v16.enums import ConfigurationStatus

from .action_errors import (
    raise_action_validation,
    raise_charger_disconnected,
    raise_write_blocked,
)
from .charging_controls import (
    PV_LINKAGE_WORKING_MODES,
    ChargingControl,
    available_working_mode_options,
    control_write_block_reason,
    encode_control_value,
    encode_working_mode,
    selected_working_mode,
)
from .configuration import (
    CONFIGURATION_ENTITY_OPTIONS,
    configuration_entity_state,
)
from .configuration_control import GrowattConfigurationControlMixin
from .configuration_writes import ConfigurationWriteStatus
from .const import DOMAIN
from .pv_linkage import PvBoostMode
from .write_queue import (
    CONFIGURATION_WRITE_POLICY,
    ChargerConnectionUnavailable,
    ChargerRequestOutcomeUncertain,
    ChargerWriteResult,
)


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Growatt THOR select entities."""
    coordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities(
        [
            WorkingModeSelect(coordinator, entry),
            AuthorizationModeSelect(coordinator, entry),
            ExternalSamplingMethodSelect(coordinator, entry),
            PowerMeterTypeSelect(coordinator, entry),
            PvBoostDraftSelect(coordinator, entry),
        ]
    )


class AuthorizationModeSelect(GrowattConfigurationControlMixin, CoordinatorEntity, SelectEntity):
    """Explicit, idle-only authorization changes; never issue a reboot or start."""

    _control = ChargingControl.AUTHORIZATION_MODE
    _attr_has_entity_name = True
    _attr_translation_key = "authorization_mode"
    _attr_icon = "mdi:card-account-details-outline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(CONFIGURATION_ENTITY_OPTIONS["G_ChargerMode"])

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self.hass = coordinator.hass
        self._attr_unique_id = f"{entry.entry_id}_authorization_mode_control"
        self._attr_device_info = {"identifiers": {(DOMAIN, entry.entry_id)}}

    @property
    def current_option(self):
        return configuration_entity_state(
            self._configuration_key,
            self._configuration_value,
        )

    @property
    def available(self):
        return super().available and self._control_available and self.current_option is not None

    async def async_select_option(self, option: str) -> None:
        await self._async_write_configuration(
            encode_control_value(self._control, option)
        )

class WorkingModeSelect(CoordinatorEntity, SelectEntity):
    """Select a charging strategy through the captured indirect writes."""

    _attr_has_entity_name = True
    _attr_translation_key = "working_mode"
    _attr_icon = "mdi:ev-station"
    _attr_entity_category = EntityCategory.CONFIG
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self.hass = coordinator.hass
        self._pending_option: str | None = None
        self._intent_sequence = 0
        self._pending_intent: int | None = None
        self._readback_task: asyncio.Task | None = None
        self._attr_unique_id = f"{entry.entry_id}_working_mode_control"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }

    @property
    def current_option(self):
        if self._pending_option is not None:
            return self._pending_option
        return selected_working_mode(self.coordinator.configuration_values)

    @property
    def options(self):
        return available_working_mode_options(
            self.current_option,
            external_meter_ready=self.coordinator.external_meter_ready_for_pv,
        )

    @property
    def available(self):
        # An active charging transaction prevents mode changes, but the last
        # reported strategy remains useful state and must stay visible.
        return (
            super().available
            and self.coordinator.connected
            and self.current_option is not None
        )

    @property
    def _write_block_reason(self) -> str | None:
        return control_write_block_reason(
            ChargingControl.WORKING_MODE,
            self.coordinator.configuration_values,
            connected=self.coordinator.connected,
            transaction_active=self.coordinator.transaction_is_active,
            charger_faulted=self.coordinator.charger_is_faulted,
        )

    @property
    def extra_state_attributes(self):
        return {"information": "details"}

    async def async_select_option(self, option: str) -> None:
        if option == self.current_option:
            return
        if option not in self.options:
            _LOGGER.warning(
                "Cannot select PV Linkage while external meter health is %s",
                self.coordinator.external_meter_health,
            )
            raise_action_validation(
                (
                    "external_meter_not_ready"
                    if option in PV_LINKAGE_WORKING_MODES
                    else "invalid_working_mode"
                ),
                placeholders={"option": option},
            )
        block_reason = self._write_block_reason
        if block_reason is not None:
            _LOGGER.warning("Cannot change working mode: %s", block_reason)
            raise_write_blocked(block_reason)
        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if charge_point is None:
            _LOGGER.warning("Cannot change working mode: charger not connected")
            raise_charger_disconnected()
        key, raw_value = encode_working_mode(option)
        self._intent_sequence += 1
        intent = self._intent_sequence
        self._pending_option = option
        self._pending_intent = intent
        if self._readback_task is not None and not self._readback_task.done():
            self._readback_task.cancel()
        self.async_write_ha_state()
        generation = self.coordinator.begin_configuration_write(key, raw_value)
        await self.coordinator.queue_write(
            self._apply_working_mode,
            charge_point,
            key,
            raw_value,
            option,
            generation,
            intent,
            dedupe_key="working_mode",
            command_name=f"ChangeConfiguration({key})",
            requires_connection=True,
            configuration_key=key,
            configuration_generation=generation,
            policy=CONFIGURATION_WRITE_POLICY,
            on_unsent=lambda _result: self._clear_pending_option(
                option,
                intent,
            ),
        )

    async def _apply_working_mode(
        self,
        charge_point,
        key: str,
        raw_value: str,
        option: str,
        generation: int,
        intent: int,
    ) -> ChargerWriteResult:
        if (
            option in PV_LINKAGE_WORKING_MODES
            and not self.coordinator.external_meter_ready_for_pv
        ):
            _LOGGER.warning(
                "Skipping queued PV Linkage change: external meter health is %s",
                self.coordinator.external_meter_health,
            )
            self.coordinator.mark_configuration_write(
                key,
                ConfigurationWriteStatus.SKIPPED,
                generation=generation,
                result="external_meter_not_ready",
            )
            self._clear_pending_option(option, intent)
            return ChargerWriteResult.skipped("external_meter_not_ready")
        block_reason = self._write_block_reason
        if block_reason is not None:
            _LOGGER.warning("Skipping queued working mode change: %s", block_reason)
            self.coordinator.mark_configuration_write(
                key,
                ConfigurationWriteStatus.SKIPPED,
                generation=generation,
                result=block_reason,
            )
            self._clear_pending_option(option, intent)
            return ChargerWriteResult.skipped(block_reason)

        try:
            result = await charge_point.change_configuration(key, raw_value)
        except ChargerConnectionUnavailable:
            raise
        except ChargerRequestOutcomeUncertain as exc:
            self.coordinator.mark_configuration_write(
                key,
                ConfigurationWriteStatus.UNCERTAIN,
                generation=generation,
                result=str(exc),
            )
            if self._selection_is_current(option, intent):
                self._readback_task = self.hass.async_create_task(
                    self._refresh_configuration(option, intent, delay=0)
                )
            else:
                self.coordinator.schedule_configuration_refresh(delay=0)
            return ChargerWriteResult.uncertain(str(exc))
        except Exception:
            self._clear_pending_option(option, intent)
            raise
        accepted = result in {
            ConfigurationStatus.accepted,
            ConfigurationStatus.reboot_required,
        }
        outcome_is_current = self.coordinator.acknowledge_configuration_write(
            key,
            generation=generation,
            accepted=accepted,
            result=result,
        )
        if not accepted:
            _LOGGER.error("Working mode change rejected by charger: %s", result)
            self._clear_pending_option(option, intent)
            return ChargerWriteResult.failed("charger_rejected", result)

        selection_is_current = self._selection_is_current(option, intent)
        if outcome_is_current and selection_is_current:
            # Working modes use different underlying Growatt keys. Therefore
            # the entity-level intent token complements the per-key generation
            # and prevents an older mode response from winning across keys.
            self.coordinator.update_configuration_value(key, raw_value)
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

        if selection_is_current:
            self._readback_task = self.hass.async_create_task(
                self._refresh_configuration(option, intent)
            )
        else:
            # Even a superseded accepted write changed the charger briefly;
            # the shared refresh waits for the replacement before reading back.
            self.coordinator.schedule_configuration_refresh()
        return ChargerWriteResult.success(result)

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
        delay: float = 20.0,
    ) -> None:
        """Confirm the effective mode through the shared, coalesced readback."""
        try:
            refresh_task = self.coordinator.schedule_configuration_refresh(
                delay=delay
            )
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


class ExternalSamplingMethodSelect(
    GrowattConfigurationControlMixin,
    CoordinatorEntity,
    SelectEntity,
):
    """Select the captured external current sampling method."""

    _control = ChargingControl.EXTERNAL_SAMPLING_METHOD
    _attr_has_entity_name = True
    _attr_translation_key = "external_sampling_method"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:connection"
    _attr_options = list(
        CONFIGURATION_ENTITY_OPTIONS["G_ExternalSamplingCurWring"]
    )

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self.hass = coordinator.hass
        self._attr_unique_id = (
            f"{entry.entry_id}_external_sampling_method_control"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id, "grid_connection")},
            "name": "Growatt THOR External Meter",
            "manufacturer": "Growatt",
            "model": "THOR External Meter",
        }

    @property
    def current_option(self):
        return configuration_entity_state(
            self._configuration_key,
            self._configuration_value,
        )

    @property
    def available(self):
        return (
            super().available
            and self._control_available
            and self.current_option is not None
        )

    async def async_select_option(self, option: str) -> None:
        await self._async_write_configuration(
            encode_control_value(self._control, option)
        )


class PowerMeterTypeSelect(
    GrowattConfigurationControlMixin,
    CoordinatorEntity,
    SelectEntity,
):
    """Select the Modbus meter model reported through OCPP."""

    _control = ChargingControl.POWER_METER_TYPE
    _attr_has_entity_name = True
    _attr_translation_key = "power_meter_type"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:counter"
    _attr_options = list(CONFIGURATION_ENTITY_OPTIONS["G_PowerMeterType"])

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self.hass = coordinator.hass
        self._attr_unique_id = f"{entry.entry_id}_power_meter_type_control"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id, "grid_connection")},
            "name": "Growatt THOR External Meter",
            "manufacturer": "Growatt",
            "model": "THOR External Meter",
        }

    @property
    def current_option(self):
        return configuration_entity_state(
            self._configuration_key,
            self._configuration_value,
        )

    @property
    def available(self):
        return (
            super().available
            and self._control_available
            and self.current_option is not None
        )

    async def async_select_option(self, option: str) -> None:
        await self._async_write_configuration(
            encode_control_value(self._control, option)
        )


class PvBoostDraftSelect(CoordinatorEntity, SelectEntity):
    """Edit the local PV Boost mode without immediately writing the charger."""

    _attr_has_entity_name = True
    _attr_translation_key = "pv_boost_mode"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:rocket-launch-outline"
    _attr_options = [mode.value for mode in PvBoostMode]

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self.hass = coordinator.hass
        self._attr_unique_id = f"{entry.entry_id}_pv_boost_mode_draft"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }

    @property
    def current_option(self):
        mode = self.coordinator.pv_boost_mode_draft
        return mode.value if mode is not None else None

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
    def extra_state_attributes(self):
        return {"information": "details"}

    async def async_select_option(self, option: str) -> None:
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning("Cannot edit PV Boost mode: %s", block_reason)
            raise_write_blocked(block_reason)
        self.coordinator.update_pv_linkage_draft(
            pv_boost_mode_draft=PvBoostMode(option)
        )
