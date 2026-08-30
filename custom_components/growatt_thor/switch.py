"""Switch entities for Growatt THOR load balancing and LCD display."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

from ocpp.v16.enums import ConfigurationStatus

from .const import DOMAIN
from .charging_controls import (
    ChargingControl,
    charger_write_block_reason,
    control_write_block_reason,
    encode_control_value,
)
from .configuration import configuration_entity_state
from .configuration_control import (
    GrowattConfigurationControlMixin,
    async_confirm_configuration,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Growatt THOR switches."""
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities([
        LoadBalancingEnableSwitch(coordinator, entry),
        LcdDisplaySwitch(coordinator, entry),
        WarmUpSwitch(coordinator, entry),
    ])


class LoadBalancingEnableSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to enable/disable load balancing."""

    _attr_has_entity_name = True
    _attr_translation_key = "load_balancing"
    _attr_icon = "mdi:power-plug-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_load_balancing_enable"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id, "grid_connection")},
            "name": "Growatt THOR External Meter",
            "manufacturer": "Growatt",
            "model": "THOR External Meter",
        }
        self.hass = coordinator.hass

    @property
    def is_on(self):
        """Return true if load balancing is enabled."""
        return self.coordinator.external_limit_power_enable

    @property
    def available(self):
        return (
            super().available
            and self._write_block_reason is None
        )

    @property
    def _write_block_reason(self) -> str | None:
        return control_write_block_reason(
            ChargingControl.LOAD_BALANCING,
            self.coordinator.configuration_values,
            connected=self.coordinator.connected,
            transaction_active=self.coordinator.transaction_is_active,
            charger_faulted=self.coordinator.charger_is_faulted,
        )

    @property
    def extra_state_attributes(self):
        return {
            "information": "details",
            "ocpp_key": "G_ExternalLimitPowerEnable",
        }

    async def async_turn_on(self, **kwargs):
        """Enable load balancing."""
        await self._set_value("1")

    async def async_turn_off(self, **kwargs):
        """Disable load balancing."""
        await self._set_value("0")

    async def _apply_external_limit_power_enable(self, charge_point, value: str):
        """Actually write setting to the charger (runs inside write-queue)."""
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning(
                "Skipping queued Load Balancing change: %s",
                block_reason,
            )
            return
        _LOGGER.info("Setting G_ExternalLimitPowerEnable to %s", value)

        key = "G_ExternalLimitPowerEnable"
        self.coordinator.begin_configuration_write(key, value)

        result = await charge_point.change_configuration(
            key,
            value
        )

        accepted = result in {
            ConfigurationStatus.accepted,
            ConfigurationStatus.reboot_required,
        }
        self.coordinator.acknowledge_configuration_write(
            key,
            accepted=accepted,
            result=result,
        )
        if accepted:
            self.hass.async_create_task(
                async_confirm_configuration(self.hass, charge_point)
            )

        new_state = (value == "1")

        if result == ConfigurationStatus.accepted:
            self.coordinator.external_limit_power_enable = new_state
            self.coordinator.async_set_updated_data(True)
            _LOGGER.info(
                "✅ Loadbalancing enabled → %s (accepted)",
                "ON" if new_state else "OFF"
            )
        elif result == ConfigurationStatus.reboot_required:
            self.coordinator.external_limit_power_enable = new_state
            self.coordinator.async_set_updated_data(True)
            _LOGGER.warning(
                "⚠️ Loadbalancing enabled → %s (reboot required)",
                "ON" if new_state else "OFF"
            )
        else:
            _LOGGER.error("❌ Enable loadbalancing change rejected: %s", result)

    async def _set_value(self, value: str):
        """Queue the configuration update (prevents rapid-fire FW crashes)."""
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning("Cannot change Load Balancing: %s", block_reason)
            return
        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")

        if not charge_point:
            _LOGGER.warning("Cannot change Loadbalancing: charger not connected")
            return

        try:
            await self.coordinator.queue_write(
                self._apply_external_limit_power_enable,
                charge_point,
                value
            )

        except Exception as exc:
            _LOGGER.error("❌ Failed to change Loadbalancing: %s", exc, exc_info=True)


class LcdDisplaySwitch(CoordinatorEntity, SwitchEntity):
    """Switch to enable/disable LCD display (G_LCDCloseEnable)."""

    _attr_has_entity_name = True
    _attr_translation_key = "lcd_display"
    _attr_icon = "mdi:monitor"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_lcd_display"
        # Zelfde identifiers als de hoofdcharger zodat deze entity
        # verschijnt bij max stroom, charge aan/uit etc.
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }
        self.hass = coordinator.hass

    @property
    def is_on(self):
        """Return true als LCD AAN is (G_LCDCloseEnable = Disable)."""
        if self.coordinator.lcd_close_enable is None:
            return None
        return self.coordinator.lcd_close_enable == "Disable"

    @property
    def _write_block_reason(self) -> str | None:
        return charger_write_block_reason(
            connected=self.coordinator.connected,
            charger_faulted=self.coordinator.charger_is_faulted,
        )

    @property
    def available(self):
        return super().available and self._write_block_reason is None

    async def async_turn_on(self, **kwargs):
        """Zet LCD AAN (G_LCDCloseEnable = Disable)."""
        await self._set_value("Disable")

    async def async_turn_off(self, **kwargs):
        """Zet LCD UIT (G_LCDCloseEnable = Enable)."""
        await self._set_value("Enable")

    async def _apply_lcd_close_enable(self, charge_point, value: str):
        """Actually write LCD setting to the charger (runs inside write-queue)."""
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning("Skipping queued LCD display change: %s", block_reason)
            return
        _LOGGER.info("Setting G_LCDCloseEnable to %s", value)

        result = await charge_point.change_configuration(
            "G_LCDCloseEnable",
            value
        )

        if result == ConfigurationStatus.accepted:
            self.coordinator.lcd_close_enable = value
            self.coordinator.async_set_updated_data(True)
            _LOGGER.info(
                "✅ LCD display → %s (accepted)",
                "ON" if value == "Disable" else "OFF"
            )
        elif result == ConfigurationStatus.reboot_required:
            self.coordinator.lcd_close_enable = value
            self.coordinator.async_set_updated_data(True)
            _LOGGER.warning(
                "⚠️ LCD display → %s (reboot required)",
                "ON" if value == "Disable" else "OFF"
            )
        else:
            _LOGGER.error("❌ LCD display change rejected: %s", result)

    async def _set_value(self, value: str):
        """Queue the configuration update (prevents rapid-fire FW crashes)."""
        if (block_reason := self._write_block_reason) is not None:
            _LOGGER.warning("Cannot change LCD display: %s", block_reason)
            return
        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")

        if not charge_point:
            _LOGGER.warning("Cannot change LCD display: charger not connected")
            return

        try:
            await self.coordinator.queue_write(
                self._apply_lcd_close_enable,
                charge_point,
                value
            )

        except Exception as exc:
            _LOGGER.error("❌ Failed to change LCD display: %s", exc, exc_info=True)


class BaseModeAwareSwitch(
    GrowattConfigurationControlMixin,
    CoordinatorEntity,
    SwitchEntity,
):
    """Base class for verified boolean Growatt configuration controls."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry, key):
        super().__init__(coordinator)
        self.hass = coordinator.hass
        self._attr_unique_id = f"{entry.entry_id}_{key}_control"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }

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
        await self._async_write_configuration(
            encode_control_value(self._control, True)
        )

    async def async_turn_off(self, **kwargs):
        await self._async_write_configuration(
            encode_control_value(self._control, False)
        )


class WarmUpSwitch(BaseModeAwareSwitch):
    """Allow compatible vehicles to draw power after reaching full charge."""

    _control = ChargingControl.WARM_UP
    _attr_translation_key = "warm_up"
    _attr_icon = "mdi:car-defrost-front"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "warm_up")
