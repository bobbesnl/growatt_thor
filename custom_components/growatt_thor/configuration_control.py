"""Shared behavior for Growatt ChangeConfiguration entities."""
from __future__ import annotations

import logging

from ocpp.v16.enums import ConfigurationStatus

from .charging_controls import (
    CONTROL_DEFINITIONS,
    ChargingControl,
    control_is_applicable,
)
from .const import DOMAIN


_LOGGER = logging.getLogger(__name__)


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
        value = self._configuration_value
        return (
            self.coordinator.connected
            and (value is None or value.readonly is not True)
            and control_is_applicable(
                self._control,
                self.coordinator.configuration_values,
            )
        )

    @property
    def extra_state_attributes(self):
        """Expose the acknowledged raw value and a translated explanation."""
        value = self._configuration_value
        return {
            "information": "details",
            "ocpp_key": self._configuration_key,
            "raw_value": value.raw_value if value is not None else None,
        }

    async def _async_write_configuration(self, raw_value: str) -> None:
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
        result = await charge_point.change_configuration(
            self._configuration_key,
            raw_value,
        )
        if result in {
            ConfigurationStatus.accepted,
            ConfigurationStatus.reboot_required,
        }:
            self.coordinator.update_configuration_value(
                self._configuration_key,
                raw_value,
            )
            if result == ConfigurationStatus.reboot_required:
                _LOGGER.warning(
                    "%s accepted but requires a charger reboot",
                    self._configuration_key,
                )
            return

        _LOGGER.error(
            "%s change rejected by charger: %s",
            self._configuration_key,
            result,
        )
