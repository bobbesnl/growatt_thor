"""Shared behavior for Growatt ChangeConfiguration entities."""
from __future__ import annotations

import asyncio
import logging

from ocpp.v16.enums import ConfigurationStatus

from .charging_controls import (
    CONTROL_DEFINITIONS,
    ChargingControl,
    control_write_block_reason,
)
from .const import DOMAIN


_LOGGER = logging.getLogger(__name__)


async def async_confirm_configuration(hass, charge_point) -> None:
    """Request a delayed readback after the charger applies a write."""
    await asyncio.sleep(20)
    if hass.data.get(DOMAIN, {}).get("charge_point") is charge_point:
        await charge_point.trigger_get_configuration()


class GrowattConfigurationControlMixin:
    """Write one verified Growatt configuration value through the safe queue."""

    _control: ChargingControl

    @property
    def _configuration_key(self) -> str:
        return CONTROL_DEFINITIONS[self._control].configuration_key

    @property
    def _configuration_value(self):
        return self.coordinator.configuration_values.get(self._configuration_key)

    @property
    def _control_available(self) -> bool:
        return self._write_block_reason is None

    @property
    def _write_block_reason(self) -> str | None:
        return control_write_block_reason(
            self._control,
            self.coordinator.configuration_values,
            connected=self.coordinator.connected,
            transaction_active=self.coordinator.transaction_is_active,
        )

    @property
    def extra_state_attributes(self):
        """Expose the acknowledged raw value and a translated explanation."""
        value = self._configuration_value
        write = self.coordinator.configuration_writes.get(
            self._configuration_key
        )
        return {
            "information": "details",
            "ocpp_key": self._configuration_key,
            "raw_value": value.raw_value if value is not None else None,
            "write_status": write.status.value if write is not None else None,
        }

    async def _async_write_configuration(self, raw_value: str) -> None:
        block_reason = self._write_block_reason
        if block_reason is not None:
            _LOGGER.warning(
                "Cannot change %s: %s",
                self._configuration_key,
                block_reason,
            )
            return
        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if charge_point is None:
            _LOGGER.warning(
                "Cannot change %s: charger not connected",
                self._configuration_key,
            )
            return

        await self.coordinator.queue_write(
            self._apply_configuration,
            charge_point,
            raw_value,
            dedupe_key=self._configuration_key,
        )

    async def _apply_configuration(self, charge_point, raw_value: str) -> None:
        block_reason = self._write_block_reason
        if block_reason is not None:
            _LOGGER.warning(
                "Skipping queued change for %s: %s",
                self._configuration_key,
                block_reason,
            )
            return

        self.coordinator.begin_configuration_write(
            self._configuration_key,
            raw_value,
        )
        result = await charge_point.change_configuration(
            self._configuration_key,
            raw_value,
        )
        accepted = result in {
            ConfigurationStatus.accepted,
            ConfigurationStatus.reboot_required,
        }
        self.coordinator.acknowledge_configuration_write(
            self._configuration_key,
            accepted=accepted,
            result=result,
        )
        if accepted:
            self.coordinator.update_configuration_value(
                self._configuration_key,
                raw_value,
            )
            if result == ConfigurationStatus.reboot_required:
                _LOGGER.warning(
                    "%s accepted but requires a charger reboot",
                    self._configuration_key,
                )
            self.hass.async_create_task(
                async_confirm_configuration(self.hass, charge_point)
            )
            return

        _LOGGER.error(
            "%s change rejected by charger: %s",
            self._configuration_key,
            result,
        )
