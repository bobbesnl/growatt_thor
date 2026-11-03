"""Shared behavior for mode-aware Growatt ChangeConfiguration entities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..charging.control_capabilities import (
    CONTROL_DEFINITIONS,
    ChargingControl,
    control_is_applicable,
)
from .values import ConfigurationValue, configuration_value_from_item
from .writer import ConfigurationWrite, ConfigurationWriter, WritePolicy
from .writes import pending_configuration_value

if TYPE_CHECKING:
    from .contracts import ConfigurationWriteOwner

_LOGGER = logging.getLogger(__name__)


class ConfigurationControlWritePolicy(WritePolicy[str]):
    """Write one mode-aware control's already encoded wire string.

    Pending state comes from write tracking, so there is no optimistic value to
    roll back; unexpected errors propagate to the queue.
    """

    def __init__(self, owner: ConfigurationWriteOwner, control: ChargingControl) -> None:
        super().__init__(owner)
        self.control = control
        self.key = CONTROL_DEFINITIONS[control].configuration_key

    @property
    def label(self) -> str:
        return self.key

    def encode(self, value: str) -> tuple[str, str]:
        return self.key, value

    def request_block_reason(self) -> str | None:
        return self.owner.write_block_reason(self.control)

    def on_skipped(self, write: ConfigurationWrite[str], reason: str) -> None:
        _LOGGER.warning("Skipping queued change for %s: %s", write.key, reason)


class GrowattConfigurationControlMixin:
    """Write one mode-aware control with pending-state projection."""

    coordinator: ConfigurationWriteOwner
    _control: ChargingControl

    @property
    def _configuration_key(self) -> str:
        return CONTROL_DEFINITIONS[self._control].configuration_key

    @property
    def _configuration_value(self) -> ConfigurationValue | None:
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
    def _writer(self) -> ConfigurationWriter[str]:
        # Writer and policy hold no state, so a fresh pair per call behaves
        # like a retained one.
        return ConfigurationWriter(
            self.coordinator, ConfigurationControlWritePolicy(self.coordinator, self._control)
        )

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Expose stable metadata without creating attribute-only history."""
        return {
            "information": "details",
            "ocpp_key": self._configuration_key,
        }

    async def _async_write_configuration(self, raw_value: str) -> None:
        # Callers validate domain values and pass the finished OCPP wire string.
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

        await self._writer.async_request(raw_value)
