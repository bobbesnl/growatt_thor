"""Switch entities for Growatt THOR load balancing and LCD display."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .runtime.keys import ACTIVE_CHARGE_POINT

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .runtime.entry import ThorConfigEntry

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory
from ocpp.v16.enums import ConfigurationStatus

from .charging.control_capabilities import (
    ChargingControl,
    charger_write_block_reason,
    control_is_applicable,
    encode_control_value,
)
from .configuration.controls import GrowattConfigurationControlMixin, GrowattConfigurationWriteMixin
from .configuration.keys import KEY_EXTERNAL_LIMIT_POWER_ENABLE, KEY_LCDCLOSE_ENABLE
from .configuration.values import configuration_entity_state
from .configuration.writes import (
    ConfigurationWriteStatus,
    pending_configuration_value,
)
from .entity import ThorEntity
from .runtime.action_errors import (
    async_require_command_completion,
    raise_charger_disconnected,
    raise_write_blocked,
)
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
    """Set up Growatt THOR switches."""
    coordinator = entry.runtime_data.coordinator

    async_add_entities(
        [
            LoadBalancingEnableSwitch(coordinator, entry),
            LcdDisplaySwitch(coordinator, entry),
            WarmUpSwitch(coordinator, entry),
        ]
    )


class LoadBalancingEnableSwitch(GrowattConfigurationWriteMixin, ThorEntity, SwitchEntity):
    """Switch to enable/disable load balancing."""

    _attr_has_entity_name = True
    _attr_translation_key = "load_balancing"
    _attr_icon = "mdi:power-plug-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, device="meter")
        self._attr_unique_id = f"{entry.entry_id}_load_balancing_enable"

    @property
    def is_on(self):
        """Return true if load balancing is enabled."""
        desired_value = pending_configuration_value(
            self.coordinator.configuration_writes,
            KEY_EXTERNAL_LIMIT_POWER_ENABLE,
        )
        if desired_value is not None:
            return desired_value == "1"
        return self.coordinator.external_limit_power_enable

    @property
    def available(self):
        return (
            super().available
            and self.coordinator.connected
            and control_is_applicable(
                ChargingControl.LOAD_BALANCING,
                self.coordinator.configuration_values,
            )
        )

    @property
    def _write_block_reason(self) -> str | None:
        return self.coordinator.write_block_reason(ChargingControl.LOAD_BALANCING)

    @property
    def extra_state_attributes(self):
        return {
            **self.information_attributes,
            "ocpp_key": KEY_EXTERNAL_LIMIT_POWER_ENABLE,
        }

    async def async_turn_on(self, **kwargs):
        """Enable load balancing."""
        await self._set_value("1")

    async def async_turn_off(self, **kwargs):
        """Disable load balancing."""
        await self._set_value("0")

    async def _apply_external_limit_power_enable(
        self,
        charge_point,
        value: str,
        generation: int,
    ) -> ChargerWriteResult:
        """Actually write setting to the charger (runs inside write-queue)."""
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning(
                "Skipping queued Load Balancing change: %s",
                block_reason,
            )
            self.coordinator.mark_configuration_write(
                KEY_EXTERNAL_LIMIT_POWER_ENABLE,
                ConfigurationWriteStatus.SKIPPED,
                generation=generation,
                result=block_reason,
            )
            return ChargerWriteResult.skipped(block_reason)
        _LOGGER.info("Setting G_ExternalLimitPowerEnable to %s", value)

        key = KEY_EXTERNAL_LIMIT_POWER_ENABLE
        try:
            result = await self._send_configuration(charge_point, key, value)
        except ChargerConnectionUnavailable:
            raise
        except ChargerRequestOutcomeUncertain as exc:
            self.coordinator.mark_configuration_write(
                key,
                ConfigurationWriteStatus.UNCERTAIN,
                generation=generation,
                result=str(exc),
            )
            self.coordinator.schedule_configuration_refresh(delay=0)
            return ChargerWriteResult.uncertain(str(exc))

        response = self._acknowledge_configuration_response(key, generation, result)
        accepted, outcome_is_current = response.accepted, response.current
        if accepted and outcome_is_current:
            self._on_accepted(value, key=key)
        if accepted:
            self.coordinator.schedule_configuration_refresh()

        new_state = value == "1"

        if result == ConfigurationStatus.accepted:
            if outcome_is_current:
                self.coordinator.external_limit_power_enable = new_state
                self.coordinator.async_set_updated_data(True)
            _LOGGER.info("Loadbalancing enabled → %s (accepted)", "ON" if new_state else "OFF")
        elif result == ConfigurationStatus.reboot_required:
            if outcome_is_current:
                self.coordinator.external_limit_power_enable = new_state
                self.coordinator.async_set_updated_data(True)
            _LOGGER.warning(
                "Loadbalancing enabled → %s (reboot required)",
                "ON" if new_state else "OFF",
            )
        else:
            _LOGGER.error("Enable loadbalancing change rejected: %s", result)
            return ChargerWriteResult.failed("charger_rejected", result)
        return ChargerWriteResult.success(result)

    async def _set_value(self, value: str):
        """Queue the configuration update (prevents rapid-fire FW crashes)."""
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning("Cannot change Load Balancing: %s", block_reason)
            raise_write_blocked(block_reason)
        charge_point = self.coordinator.runtime_data.get(ACTIVE_CHARGE_POINT)

        if not charge_point:
            _LOGGER.warning("Cannot change Loadbalancing: charger not connected")
            raise_charger_disconnected()

        new_state = value == "1"
        if self.is_on == new_state:
            _LOGGER.debug(
                "Loadbalancing already %s - skipping write",
                "ON" if new_state else "OFF",
            )
            return

        generation = self.coordinator.begin_configuration_write(
            KEY_EXTERNAL_LIMIT_POWER_ENABLE,
            value,
        )
        handle = await self.coordinator.queue_write(
            self._apply_external_limit_power_enable,
            charge_point,
            value,
            generation,
            dedupe_key=KEY_EXTERNAL_LIMIT_POWER_ENABLE,
            command_name="ChangeConfiguration(G_ExternalLimitPowerEnable)",
            requires_connection=True,
            configuration_key=KEY_EXTERNAL_LIMIT_POWER_ENABLE,
            configuration_generation=generation,
            policy=CONFIGURATION_WRITE_POLICY,
        )
        await async_require_command_completion(handle)


class LcdDisplaySwitch(GrowattConfigurationWriteMixin, ThorEntity, SwitchEntity):
    """Switch to enable/disable LCD display (G_LCDCloseEnable)."""

    _attr_has_entity_name = True
    _attr_translation_key = "lcd_display"
    _attr_icon = "mdi:monitor"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_lcd_display"
        # Keep LCD controls on the same charger device as current and Start/Stop.

    def _on_accepted(self, raw_value, *, key=None, value=None) -> None:
        self.coordinator.lcd_close_enable = raw_value
        super()._on_accepted(raw_value, key=key, value=value)
        self.coordinator.async_set_updated_data(True)

    @property
    def is_on(self):
        """Return the desired state while a write awaits acknowledgement.

        Home Assistant refreshes a switch immediately after its service call.
        Without this explicit pending state, a queued change appeared to snap
        back for up to a minute even though it was still waiting normally.
        """
        desired_value = pending_configuration_value(
            self.coordinator.configuration_writes,
            KEY_LCDCLOSE_ENABLE,
        )
        if desired_value is not None:
            return desired_value == "Disable"
        if self.coordinator.lcd_close_enable is None:
            return None
        return self.coordinator.lcd_close_enable == "Disable"

    @property
    def extra_state_attributes(self):
        """Expose pending versus reported state for support diagnostics."""
        write = self.coordinator.configuration_writes.get(KEY_LCDCLOSE_ENABLE)
        return {
            "ocpp_key": KEY_LCDCLOSE_ENABLE,
            "write_status": write.status.value if write is not None else None,
            "reported_state": self.coordinator.lcd_close_enable,
        }

    @property
    def _write_block_reason(self) -> str | None:
        return charger_write_block_reason(
            connected=self.coordinator.connected,
            charger_faulted=self.coordinator.charger_is_faulted,
        )

    @property
    def available(self):
        # A fault can block changing the LCD without invalidating its last
        # reported (or currently pending) state.
        return super().available and self.coordinator.connected and self.is_on is not None

    async def async_turn_on(self, **kwargs):
        """Turn the LCD on (G_LCDCloseEnable = Disable)."""
        await self._set_value("Disable")

    async def async_turn_off(self, **kwargs):
        """Turn the LCD off (G_LCDCloseEnable = Enable)."""
        await self._set_value("Enable")

    async def _apply_lcd_close_enable(
        self,
        charge_point,
        value: str,
        generation: int,
    ) -> ChargerWriteResult:
        """Actually write LCD setting to the charger (runs inside write-queue)."""
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning("Skipping queued LCD display change: %s", block_reason)
            self.coordinator.mark_configuration_write(
                KEY_LCDCLOSE_ENABLE,
                ConfigurationWriteStatus.SKIPPED,
                generation=generation,
                result=block_reason,
            )
            return ChargerWriteResult.skipped(block_reason)
        _LOGGER.info("Setting G_LCDCloseEnable to %s", value)

        key = KEY_LCDCLOSE_ENABLE
        try:
            result = await self._send_configuration(charge_point, key, value)
        except ChargerConnectionUnavailable:
            raise
        except ChargerRequestOutcomeUncertain as exc:
            self.coordinator.mark_configuration_write(
                key,
                ConfigurationWriteStatus.UNCERTAIN,
                generation=generation,
                result=str(exc),
            )
            self.coordinator.schedule_configuration_refresh(delay=0)
            return ChargerWriteResult.uncertain(str(exc))

        response = self._acknowledge_configuration_response(key, generation, result)
        outcome_is_current = response.current

        if result == ConfigurationStatus.accepted:
            if outcome_is_current:
                self._on_accepted(value, key=key)
            _LOGGER.info("LCD display → %s (accepted)", "ON" if value == "Disable" else "OFF")
        elif result == ConfigurationStatus.reboot_required:
            if outcome_is_current:
                self._on_accepted(value, key=key)
            _LOGGER.warning(
                "LCD display → %s (reboot required)",
                "ON" if value == "Disable" else "OFF",
            )
        else:
            _LOGGER.error("LCD display change rejected: %s", result)
            self.coordinator.async_set_updated_data(True)
            return ChargerWriteResult.failed("charger_rejected", result)

        self.coordinator.schedule_configuration_refresh()
        return ChargerWriteResult.success(result)

    async def _set_value(self, value: str):
        """Queue the configuration update (prevents rapid-fire FW crashes)."""
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning("Cannot change LCD display: %s", block_reason)
            raise_write_blocked(block_reason)
        charge_point = self.coordinator.runtime_data.get(ACTIVE_CHARGE_POINT)

        if not charge_point:
            _LOGGER.warning("Cannot change LCD display: charger not connected")
            raise_charger_disconnected()

        desired_value = pending_configuration_value(
            self.coordinator.configuration_writes,
            KEY_LCDCLOSE_ENABLE,
        )
        effective_value = (
            desired_value if desired_value is not None else self.coordinator.lcd_close_enable
        )
        if effective_value == value:
            _LOGGER.debug(
                "LCD display already %s - skipping write",
                "ON" if value == "Disable" else "OFF",
            )
            return

        # Begin tracking before enqueueing so ``is_on`` can expose the user's
        # desired value during the rate-limit wait.
        generation = self.coordinator.begin_configuration_write(
            KEY_LCDCLOSE_ENABLE,
            value,
        )
        handle = await self.coordinator.queue_write(
            self._apply_lcd_close_enable,
            charge_point,
            value,
            generation,
            dedupe_key=KEY_LCDCLOSE_ENABLE,
            command_name="ChangeConfiguration(G_LCDCloseEnable)",
            requires_connection=True,
            configuration_key=KEY_LCDCLOSE_ENABLE,
            configuration_generation=generation,
            policy=CONFIGURATION_WRITE_POLICY,
        )
        await async_require_command_completion(handle)


class BaseModeAwareSwitch(
    GrowattConfigurationControlMixin,
    ThorEntity,
    SwitchEntity,
):
    """Base class for verified boolean Growatt configuration controls."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry, key):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{key}_control"

    @property
    def is_on(self):
        state = configuration_entity_state(
            self._configuration_key,
            self._configuration_value,
        )
        if state is None:
            return None
        return state == "enabled"

    @property
    def available(self):
        return super().available and self._control_available

    async def async_turn_on(self, **kwargs):
        await self._async_write_configuration(encode_control_value(self._control, True))

    async def async_turn_off(self, **kwargs):
        await self._async_write_configuration(encode_control_value(self._control, False))


class WarmUpSwitch(BaseModeAwareSwitch):
    """Allow compatible vehicles to draw power after reaching full charge."""

    _control = ChargingControl.WARM_UP
    _attr_translation_key = "warm_up"
    _attr_icon = "mdi:car-defrost-front"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "warm_up")
