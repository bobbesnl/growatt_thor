"""Switch entities for Growatt THOR load balancing and LCD display."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import GrowattCoordinator
    from .runtime.entry import ThorConfigEntry

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from ocpp.v16.enums import ConfigurationStatus

from .charging.control_capabilities import (
    ChargingControl,
    charger_write_block_reason,
    control_is_applicable,
    encode_control_value,
)
from .configuration.controls import ConfigurationControl
from .configuration.keys import KEY_EXTERNAL_LIMIT_POWER_ENABLE, KEY_LCDCLOSE_ENABLE
from .configuration.writer import ConfigurationWrite, ConfigurationWriter, WritePolicy
from .configuration.writes import (
    pending_configuration_value,
)
from .entity import ThorEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ThorConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Growatt THOR switches."""
    # HA forwards platforms only after this entry has claimed its coordinator.
    coordinator = cast("GrowattCoordinator", entry.runtime_data.coordinator)

    async_add_entities(
        [
            LoadBalancingEnableSwitch(coordinator, entry),
            LcdDisplaySwitch(coordinator, entry),
            *(
                ConfigurationControlSwitch(coordinator, entry, description)
                for description in CONTROL_SWITCHES
            ),
        ]
    )


class LoadBalancingEnableWritePolicy(WritePolicy[str]):
    """Write G_ExternalLimitPowerEnable; pending state comes from write tracking."""

    label = "Load Balancing"
    # Acknowledge and schedule readback before updating the enabled observation.
    refreshes_on_apply = True

    def __init__(self, entity: LoadBalancingEnableSwitch) -> None:
        super().__init__(entity.coordinator)
        self.entity = entity
        self.coordinator = entity.coordinator

    def encode(self, value: str) -> tuple[str, str]:
        return KEY_EXTERNAL_LIMIT_POWER_ENABLE, value

    def request_block_reason(self) -> str | None:
        return self.coordinator.write_block_reason(ChargingControl.LOAD_BALANCING)

    def is_unchanged(self, value: str) -> bool:
        new_state = value == "1"
        if self.entity.is_on != new_state:
            return False
        _LOGGER.debug("Loadbalancing already %s - skipping write", "ON" if new_state else "OFF")
        return True

    def on_skipped(self, write: ConfigurationWrite[str], reason: str) -> None:
        _LOGGER.warning("Skipping queued Load Balancing change: %s", reason)

    def apply_accepted(self, write: ConfigurationWrite[str]) -> None:
        super().apply_accepted(write)
        self.coordinator.schedule_configuration_refresh()
        self.coordinator.external_limit_power_enable = write.value == "1"
        self.coordinator.async_set_updated_data(True)

    def report_accepted(self, write: ConfigurationWrite[str], result: object) -> None:
        state = "ON" if write.value == "1" else "OFF"
        if result == ConfigurationStatus.reboot_required:
            _LOGGER.warning("Loadbalancing enabled → %s (reboot required)", state)
        else:
            _LOGGER.info("Loadbalancing enabled → %s (accepted)", state)

    def on_rejected(self, write: ConfigurationWrite[str], result: object) -> None:
        _LOGGER.error("Enable loadbalancing change rejected: %s", result)


class LoadBalancingEnableSwitch(ThorEntity, SwitchEntity):
    """Switch to enable/disable load balancing."""

    coordinator: GrowattCoordinator

    _attr_has_entity_name = True
    _attr_translation_key = "load_balancing"
    _attr_icon = "mdi:power-plug-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: GrowattCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, device="meter")
        self._attr_unique_id = f"{entry.entry_id}_load_balancing_enable"
        self._writer = ConfigurationWriter(coordinator, LoadBalancingEnableWritePolicy(self))

    @property
    def is_on(self) -> bool | None:
        """Return true if load balancing is enabled."""
        desired_value = pending_configuration_value(
            self.coordinator.configuration_writes,
            KEY_EXTERNAL_LIMIT_POWER_ENABLE,
        )
        if desired_value is not None:
            return desired_value == "1"
        return self.coordinator.external_limit_power_enable

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.connected
            and control_is_applicable(
                ChargingControl.LOAD_BALANCING,
                self.coordinator.configuration_values,
            )
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return {
            **self.information_attributes,
            "ocpp_key": KEY_EXTERNAL_LIMIT_POWER_ENABLE,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable load balancing."""
        await self._set_value("1")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable load balancing."""
        await self._set_value("0")

    async def _set_value(self, value: str) -> None:
        """Queue the configuration update (prevents rapid-fire FW crashes)."""
        await self._writer.async_request(value)


class LcdDisplayWritePolicy(WritePolicy[str]):
    """Write G_LCDCloseEnable ("Disable" means the display is on)."""

    label = "LCD display"

    def __init__(self, entity: LcdDisplaySwitch) -> None:
        super().__init__(entity.coordinator)
        self.entity = entity
        self.coordinator = entity.coordinator

    def encode(self, value: str) -> tuple[str, str]:
        return KEY_LCDCLOSE_ENABLE, value

    def request_block_reason(self) -> str | None:
        return charger_write_block_reason(
            connected=self.coordinator.connected,
            charger_faulted=self.coordinator.charger_is_faulted,
        )

    def is_unchanged(self, value: str) -> bool:
        desired_value = pending_configuration_value(
            self.coordinator.configuration_writes,
            KEY_LCDCLOSE_ENABLE,
        )
        effective_value = (
            desired_value if desired_value is not None else self.coordinator.lcd_close_enable
        )
        if effective_value != value:
            return False
        _LOGGER.debug(
            "LCD display already %s - skipping write",
            "ON" if value == "Disable" else "OFF",
        )
        return True

    def on_skipped(self, write: ConfigurationWrite[str], reason: str) -> None:
        _LOGGER.warning("Skipping queued LCD display change: %s", reason)

    def apply_accepted(self, write: ConfigurationWrite[str]) -> None:
        # Update the LCD observation before the reported configuration.
        self.coordinator.lcd_close_enable = write.raw_value
        super().apply_accepted(write)
        self.coordinator.async_set_updated_data(True)

    def report_accepted(self, write: ConfigurationWrite[str], result: object) -> None:
        state = "ON" if write.value == "Disable" else "OFF"
        if result == ConfigurationStatus.reboot_required:
            _LOGGER.warning("LCD display → %s (reboot required)", state)
        else:
            _LOGGER.info("LCD display → %s (accepted)", state)

    def on_rejected(self, write: ConfigurationWrite[str], result: object) -> None:
        _LOGGER.error("LCD display change rejected: %s", result)
        self.coordinator.async_set_updated_data(True)


class LcdDisplaySwitch(ThorEntity, SwitchEntity):
    """Switch to enable/disable LCD display (G_LCDCloseEnable)."""

    coordinator: GrowattCoordinator

    _attr_has_entity_name = True
    _attr_translation_key = "lcd_display"
    _attr_icon = "mdi:monitor"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: GrowattCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_lcd_display"
        # Keep LCD controls on the same charger device as current and Start/Stop.
        self._writer = ConfigurationWriter(coordinator, LcdDisplayWritePolicy(self))

    @property
    def is_on(self) -> bool | None:
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
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose pending versus reported state for support diagnostics."""
        write = self.coordinator.configuration_writes.get(KEY_LCDCLOSE_ENABLE)
        return {
            "ocpp_key": KEY_LCDCLOSE_ENABLE,
            "write_status": write.status.value if write is not None else None,
            "reported_state": self.coordinator.lcd_close_enable,
        }

    @property
    def available(self) -> bool:
        # A fault can block changing the LCD without invalidating its last
        # reported (or currently pending) state.
        return super().available and self.coordinator.connected and self.is_on is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the LCD on (G_LCDCloseEnable = Disable)."""
        await self._set_value("Disable")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the LCD off (G_LCDCloseEnable = Enable)."""
        await self._set_value("Enable")

    async def _set_value(self, value: str) -> None:
        """Queue the configuration update (prevents rapid-fire FW crashes).

        Write tracking begins before enqueueing so ``is_on`` can expose the
        user's desired value during the rate-limit wait.
        """
        await self._writer.async_request(value)


@dataclass(frozen=True, kw_only=True)
class ConfigurationControlSwitchDescription:
    """Declare one verified boolean control; the unique ID is ``<entry>_<key>_control``."""

    key: str
    control: ChargingControl
    icon: str


CONTROL_SWITCHES = (
    # Allow compatible vehicles to draw power after reaching full charge.
    ConfigurationControlSwitchDescription(
        key="warm_up",
        control=ChargingControl.WARM_UP,
        icon="mdi:car-defrost-front",
    ),
)


class ConfigurationControlSwitch(ThorEntity, SwitchEntity):
    """Write one verified boolean Growatt configuration control."""

    coordinator: GrowattCoordinator

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: GrowattCoordinator,
        entry: ConfigEntry,
        description: ConfigurationControlSwitchDescription,
    ) -> None:
        super().__init__(coordinator, entry)
        self._description = description
        self._configuration = ConfigurationControl(coordinator, description.control)
        self._attr_unique_id = f"{entry.entry_id}_{description.key}_control"
        self._attr_translation_key = description.key
        self._attr_icon = description.icon

    @property
    def is_on(self) -> bool | None:
        state = self._configuration.state
        if state is None:
            return None
        return state == "enabled"

    @property
    def available(self) -> bool:
        return super().available and self._configuration.available

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return self._configuration.attributes

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._configuration.async_write(encode_control_value(self._description.control, True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._configuration.async_write(
            encode_control_value(self._description.control, False)
        )
