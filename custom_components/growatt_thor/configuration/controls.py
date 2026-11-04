"""Shared behavior for mode-aware Growatt ChangeConfiguration entities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..charging.control_capabilities import (
    CONTROL_DEFINITIONS,
    ChargingControl,
    control_is_applicable,
)
from .values import (
    ConfigurationScalar,
    ConfigurationValue,
    configuration_entity_state,
    configuration_value_from_item,
)
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


class ConfigurationControl:
    """Pending-state projection and write entry for one mode-aware control.

    Entities hold one instance and delegate to it; it keeps no state of its
    own besides the control it projects.
    """

    __slots__ = ("_owner", "_writer", "control", "key")

    def __init__(self, owner: ConfigurationWriteOwner, control: ChargingControl) -> None:
        self._owner = owner
        self.control = control
        self.key = CONTROL_DEFINITIONS[control].configuration_key
        self._writer = ConfigurationWriter(owner, ConfigurationControlWritePolicy(owner, control))

    @property
    def value(self) -> ConfigurationValue | None:
        reported = self._owner.configuration_values.get(self.key)
        pending_raw_value = pending_configuration_value(self._owner.configuration_writes, self.key)
        if pending_raw_value is None:
            return reported
        # Configuration entities should display the latest queued intent. The
        # reported snapshot remains untouched and is used again once the write
        # reaches a terminal rejected, skipped, or mismatching state.
        return configuration_value_from_item(
            {
                "key": self.key,
                "value": pending_raw_value,
                "readonly": (reported.readonly if reported is not None else False),
            }
        )

    @property
    def state(self) -> ConfigurationScalar:
        """The normalized entity state of the shown value."""
        return configuration_entity_state(self.key, self.value)

    @property
    def available(self) -> bool:
        """Return whether a reported value can still be shown in Home Assistant.

        Availability describes whether state is known, not whether a new value
        may safely be written right now.  In particular, an active transaction
        blocks configuration writes but must not erase the last reported value
        from the UI.
        """
        return (
            self._owner.connected
            and control_is_applicable(self.control, self._owner.configuration_values)
            and self.value is not None
        )

    @property
    def attributes(self) -> dict[str, str]:
        """Expose stable metadata without creating attribute-only history."""
        return {
            "information": "details",
            "ocpp_key": self.key,
        }

    async def async_write(self, raw_value: str) -> None:
        # Callers validate domain values and pass the finished OCPP wire string.
        pending_raw_value = pending_configuration_value(self._owner.configuration_writes, self.key)
        if pending_raw_value == raw_value:
            # Repeating an already pending action is idempotent. In contrast,
            # selecting the last reported value while a different value is
            # pending must create a new generation and supersede that request.
            return
        shown = self.value
        if pending_raw_value is None and shown is not None and shown.raw_value == raw_value:
            return

        await self._writer.async_request(raw_value)


class GrowattConfigurationControlMixin:
    """Delegate one mode-aware entity to a ConfigurationControl."""

    coordinator: ConfigurationWriteOwner
    _control: ChargingControl

    @property
    def _configuration(self) -> ConfigurationControl:
        # The control holds no state, so a fresh one per access behaves like
        # a retained one.
        return ConfigurationControl(self.coordinator, self._control)

    @property
    def _configuration_key(self) -> str:
        return CONTROL_DEFINITIONS[self._control].configuration_key

    @property
    def _configuration_value(self) -> ConfigurationValue | None:
        return self._configuration.value

    @property
    def _control_available(self) -> bool:
        return self._configuration.available

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return self._configuration.attributes

    async def _async_write_configuration(self, raw_value: str) -> None:
        await self._configuration.async_write(raw_value)
