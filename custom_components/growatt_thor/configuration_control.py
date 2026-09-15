"""Shared behavior for Growatt ChangeConfiguration entities."""
from __future__ import annotations

import logging

from ocpp.v16.enums import ConfigurationStatus

from .action_errors import raise_charger_disconnected, raise_write_blocked
from .charging_controls import (
    CONTROL_DEFINITIONS,
    ChargingControl,
    control_is_applicable,
    control_write_block_reason,
)
from .configuration_writes import ConfigurationWriteStatus
from .const import DOMAIN
from .write_queue import (
    ChargerConnectionUnavailable,
    ChargerRequestOutcomeUncertain,
    ChargerWriteResult,
)


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
        """Return whether a reported value can still be shown in Home Assistant.

        Availability describes whether state is known, not whether a new value
        may safely be written right now.  In particular, an active transaction
        blocks configuration writes but must not erase the last reported value
        from the UI.
        """
        return (
            self.coordinator.connected
            and control_is_applicable(
                self._control,
                self.coordinator.configuration_values,
            )
            and self._configuration_value is not None
        )

    @property
    def _write_block_reason(self) -> str | None:
        return control_write_block_reason(
            self._control,
            self.coordinator.configuration_values,
            connected=self.coordinator.connected,
            transaction_active=self.coordinator.transaction_is_active,
            charger_faulted=self.coordinator.charger_is_faulted,
        )

    @property
    def extra_state_attributes(self):
        """Expose stable metadata without creating attribute-only history."""
        return {
            "information": "details",
            "ocpp_key": self._configuration_key,
        }

    async def _async_write_configuration(self, raw_value: str) -> None:
        block_reason = self._write_block_reason
        if block_reason is not None:
            _LOGGER.warning(
                "Cannot change %s: %s",
                self._configuration_key,
                block_reason,
            )
            # Entity methods are HA action handlers. Raising here makes a
            # blocked automation visible in its trace instead of reporting a
            # successful call for a command that was never queued.
            raise_write_blocked(block_reason)
        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if charge_point is None:
            _LOGGER.warning(
                "Cannot change %s: charger not connected",
                self._configuration_key,
            )
            raise_charger_disconnected()

        # Record the desired value while it is still waiting in the queue.  It
        # remains separate from configuration_values, which always represents
        # the last value reported or acknowledged by the THOR.
        self.coordinator.begin_configuration_write(
            self._configuration_key,
            raw_value,
        )
        await self.coordinator.queue_write(
            self._apply_configuration,
            charge_point,
            raw_value,
            dedupe_key=self._configuration_key,
            command_name=f"ChangeConfiguration({self._configuration_key})",
            requires_connection=True,
            configuration_key=self._configuration_key,
        )

    async def _apply_configuration(
        self,
        charge_point,
        raw_value: str,
    ) -> ChargerWriteResult:
        block_reason = self._write_block_reason
        if block_reason is not None:
            _LOGGER.warning(
                "Skipping queued change for %s: %s",
                self._configuration_key,
                block_reason,
            )
            self.coordinator.mark_configuration_write(
                self._configuration_key,
                ConfigurationWriteStatus.SKIPPED,
                result=block_reason,
            )
            return ChargerWriteResult.skipped(block_reason)

        try:
            result = await charge_point.change_configuration(
                self._configuration_key,
                raw_value,
            )
        except ChargerConnectionUnavailable:
            # The queue can safely rebind and retry because no request reached
            # the OCPP layer.
            raise
        except ChargerRequestOutcomeUncertain as exc:
            self.coordinator.mark_configuration_write(
                self._configuration_key,
                ConfigurationWriteStatus.UNCERTAIN,
                result=str(exc),
            )
            self.coordinator.schedule_configuration_refresh(delay=0)
            return ChargerWriteResult.uncertain(str(exc))

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
            self.coordinator.schedule_configuration_refresh()
            return ChargerWriteResult.success(result)

        _LOGGER.error(
            "%s change rejected by charger: %s",
            self._configuration_key,
            result,
        )
        return ChargerWriteResult.failed("charger_rejected", result)
