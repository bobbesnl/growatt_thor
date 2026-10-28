"""Shared behavior for Growatt ChangeConfiguration entities."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ocpp.v16.enums import ConfigurationStatus

from ..charging.control_capabilities import (
    CONTROL_DEFINITIONS,
    ChargingControl,
    control_is_applicable,
)
from ..runtime.action_errors import (
    async_require_command_completion,
    raise_charger_disconnected,
    raise_write_blocked,
)
from ..runtime.write_results import (
    CONFIGURATION_WRITE_POLICY,
    ChargerConnectionUnavailable,
    ChargerRequestOutcomeUncertain,
    ChargerWriteResult,
)
from .values import configuration_value_from_item
from .writes import (
    ConfigurationWriteStatus,
    pending_configuration_value,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ConfigurationWriteResponse:
    """One charger acknowledgement, distinct from the current UI intent."""

    result: object
    accepted: bool
    current: bool


class GrowattConfigurationControlMixin:
    """Write one verified Growatt configuration value through the safe queue."""

    _control: ChargingControl

    def _validate_write_value(self, value):
        """Retain boundary-specific validation in the entity that owns it."""
        return value

    def _encode(self, value):
        """The default boundary already receives an encoded wire string."""
        return value

    def _on_accepted(self, raw_value: str, *, key=None, value=None) -> None:
        """Apply reported state only after the caller checked current intent."""
        self.coordinator.update_configuration_value(key or self._configuration_key, raw_value)

    def _restore_optimistic(self, generation: int, *, previous=None) -> None:
        """Entities with optimistic local state retain their own rollback policy."""

    async def _send_configuration(self, charge_point, key: str, raw_value: str):
        """Called only from the coordinator-owned write-queue callback."""
        return await charge_point.change_configuration(key, raw_value)

    def _acknowledge_configuration_response(self, key, generation, result):
        accepted = result in {ConfigurationStatus.accepted, ConfigurationStatus.reboot_required}
        current = self.coordinator.acknowledge_configuration_write(
            key, generation=generation, accepted=accepted, result=result
        )
        return ConfigurationWriteResponse(result, accepted, current)

    async def _configuration_exchange(self, charge_point, key, raw_value, generation):
        """For callbacks whose existing error boundary includes acknowledgement."""
        result = await self._send_configuration(charge_point, key, raw_value)
        return self._acknowledge_configuration_response(key, generation, result)

    @property
    def _configuration_key(self) -> str:
        return CONTROL_DEFINITIONS[self._control].configuration_key

    @property
    def _configuration_value(self):
        reported = self.coordinator.configuration_values.get(self._configuration_key)
        pending_raw_value = pending_configuration_value(
            self.coordinator.configuration_writes,
            self._configuration_key,
        )
        if pending_raw_value is None:
            return reported
        # Configuration entities should display the latest queued intent. The
        # reported snapshot remains untouched and is used again once the write
        # reaches a terminal rejected, skipped, or mismatching state.
        return configuration_value_from_item(
            {
                "key": self._configuration_key,
                "value": pending_raw_value,
                "readonly": (reported.readonly if reported is not None else False),
            }
        )

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
        return self.coordinator.write_block_reason(self._control)

    @property
    def extra_state_attributes(self):
        """Expose stable metadata without creating attribute-only history."""
        return {
            "information": "details",
            "ocpp_key": self._configuration_key,
        }

    async def _async_write_configuration(self, raw_value: str) -> None:
        raw_value = self._encode(self._validate_write_value(raw_value))
        pending_raw_value = pending_configuration_value(
            self.coordinator.configuration_writes,
            self._configuration_key,
        )
        if pending_raw_value == raw_value:
            # Repeating an already pending action is idempotent. In contrast,
            # selecting the last reported value while a different value is
            # pending must create a new generation and supersede that request.
            return
        if (
            pending_raw_value is None
            and self._configuration_value is not None
            and self._configuration_value.raw_value == raw_value
        ):
            return

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
        charge_point = self.coordinator.runtime_data.get("charge_point")
        if charge_point is None:
            _LOGGER.warning(
                "Cannot change %s: charger not connected",
                self._configuration_key,
            )
            raise_charger_disconnected()

        # Record the desired value while it is still waiting in the queue.  It
        # remains separate from configuration_values, which always represents
        # the last value reported or acknowledged by the THOR.
        generation = self.coordinator.begin_configuration_write(
            self._configuration_key,
            raw_value,
        )
        handle = await self.coordinator.queue_write(
            self._apply_configuration,
            charge_point,
            raw_value,
            generation,
            dedupe_key=self._configuration_key,
            command_name=f"ChangeConfiguration({self._configuration_key})",
            requires_connection=True,
            configuration_key=self._configuration_key,
            configuration_generation=generation,
            policy=CONFIGURATION_WRITE_POLICY,
        )
        await async_require_command_completion(handle)

    async def _apply_configuration(
        self,
        charge_point,
        raw_value: str,
        generation: int,
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
                generation=generation,
                result=block_reason,
            )
            return ChargerWriteResult.skipped(block_reason)

        try:
            result = await self._send_configuration(
                charge_point, self._configuration_key, raw_value
            )
        except ChargerConnectionUnavailable:
            # The queue can safely rebind and retry because no request reached
            # the OCPP layer.
            raise
        except ChargerRequestOutcomeUncertain as exc:
            self.coordinator.mark_configuration_write(
                self._configuration_key,
                ConfigurationWriteStatus.UNCERTAIN,
                generation=generation,
                result=str(exc),
            )
            self.coordinator.schedule_configuration_refresh(delay=0)
            return ChargerWriteResult.uncertain(str(exc))

        response = self._acknowledge_configuration_response(
            self._configuration_key, generation, result
        )
        accepted, outcome_is_current = response.accepted, response.current
        if accepted:
            # The charger may accept an older request after a newer automation
            # has already queued its replacement. Keep the accepted physical
            # outcome for readback, but expose only the newest intent in HA.
            if outcome_is_current:
                self._on_accepted(raw_value)
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
