"""Select entities for verified Growatt THOR charging controls."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from ocpp.v16.enums import ConfigurationStatus

from .charging_controls import (
    ChargingControl,
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
from .const import DOMAIN
from .pv_linkage import PvBoostMode


_LOGGER = logging.getLogger(__name__)
WORKING_MODE_OPTIONS = ["fast", "pv_linkage", "pv_linkage_plus", "off_peak"]


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Growatt THOR select entities."""
    coordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities(
        [
            WorkingModeSelect(coordinator, entry),
            ExternalSamplingMethodSelect(coordinator, entry),
            PowerMeterTypeSelect(coordinator, entry),
            PvBoostDraftSelect(coordinator, entry),
        ]
    )


class WorkingModeSelect(CoordinatorEntity, SelectEntity):
    """Select a charging strategy through the captured indirect writes."""

    _attr_has_entity_name = True
    _attr_translation_key = "working_mode"
    _attr_icon = "mdi:ev-station"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = WORKING_MODE_OPTIONS

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self.hass = coordinator.hass
        self._pending_option: str | None = None
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
    def available(self):
        return (
            super().available
            and self.current_option is not None
            and self._write_block_reason is None
        )

    @property
    def _write_block_reason(self) -> str | None:
        return control_write_block_reason(
            ChargingControl.WORKING_MODE,
            self.coordinator.configuration_values,
            connected=self.coordinator.connected,
            transaction_active=self.coordinator.transaction_is_active,
        )

    @property
    def extra_state_attributes(self):
        return {"information": "details"}

    async def async_select_option(self, option: str) -> None:
        block_reason = self._write_block_reason
        if block_reason is not None:
            _LOGGER.warning("Cannot change working mode: %s", block_reason)
            return
        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if charge_point is None:
            _LOGGER.warning("Cannot change working mode: charger not connected")
            return
        key, raw_value = encode_working_mode(option)
        self._pending_option = option
        if self._readback_task is not None and not self._readback_task.done():
            self._readback_task.cancel()
        self.async_write_ha_state()
        await self.coordinator.queue_write(
            self._apply_working_mode,
            charge_point,
            key,
            raw_value,
            option,
            dedupe_key="working_mode",
        )

    async def _apply_working_mode(
        self,
        charge_point,
        key: str,
        raw_value: str,
        option: str,
    ) -> None:
        block_reason = self._write_block_reason
        if block_reason is not None:
            _LOGGER.warning("Skipping queued working mode change: %s", block_reason)
            self._clear_pending_option(option)
            return

        self.coordinator.begin_configuration_write(key, raw_value)
        try:
            result = await charge_point.change_configuration(key, raw_value)
        except Exception:
            self._clear_pending_option(option)
            raise
        accepted = result in {
            ConfigurationStatus.accepted,
            ConfigurationStatus.reboot_required,
        }
        self.coordinator.acknowledge_configuration_write(
            key,
            accepted=accepted,
            result=result,
        )
        if not accepted:
            _LOGGER.error("Working mode change rejected by charger: %s", result)
            self._clear_pending_option(option)
            return

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

        if self._pending_option == option:
            self._readback_task = self.hass.async_create_task(
                self._refresh_configuration(charge_point, option)
            )

    def _clear_pending_option(self, option: str) -> None:
        """Clear only the pending selection owned by this write."""
        if self._pending_option == option:
            self._pending_option = None
            self.async_write_ha_state()

    async def _refresh_configuration(self, charge_point, option: str) -> None:
        """Confirm the effective mode after the charger has applied the write."""
        try:
            await asyncio.sleep(20)
            if self.hass.data.get(DOMAIN, {}).get("charge_point") is charge_point:
                await charge_point.trigger_get_configuration()
        except asyncio.CancelledError:
            return
        finally:
            self._clear_pending_option(option)

    async def async_will_remove_from_hass(self) -> None:
        """Cancel a delayed mode readback when the entity is removed."""
        self._pending_option = None
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
        )

    @property
    def available(self):
        return (
            super().available
            and self._write_block_reason is None
            and self.current_option is not None
        )

    @property
    def extra_state_attributes(self):
        return {"information": "details"}

    async def async_select_option(self, option: str) -> None:
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning("Cannot edit PV Boost mode: %s", block_reason)
            return
        self.coordinator.update_pv_linkage_draft(
            pv_boost_mode_draft=PvBoostMode(option)
        )
