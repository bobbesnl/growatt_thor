"""Capabilities needed by queued configuration entities."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import TYPE_CHECKING, Any, Protocol

from ..const import CONFIGURATION_WRITE_SPACING_SECONDS

if TYPE_CHECKING:
    from ..charging.control_capabilities import ChargingControl
    from ..runtime.write_results import ChargerCommandHandle
    from .values import ConfigurationValue
    from .writes import ConfigurationWriteState, ConfigurationWriteStatus


class ConfigurationTransport(Protocol):
    async def change_configuration(self, key: str, raw_value: str) -> object: ...


class ConfigurationWriteOwner(Protocol):
    connected: bool
    configuration_values: dict[str, ConfigurationValue]
    configuration_writes: dict[str, ConfigurationWriteState]

    @property
    def runtime_data(self) -> MutableMapping[str, Any]: ...

    def update_configuration_value(self, key: str, raw_value: str) -> None: ...

    def write_block_reason(self, control: ChargingControl) -> str | None: ...

    def begin_configuration_write(self, key: str, raw_value: str) -> int: ...

    def acknowledge_configuration_write(
        self, key: str, *, generation: int, accepted: bool, result: object
    ) -> bool: ...

    def mark_configuration_write(
        self,
        key: str,
        status: ConfigurationWriteStatus,
        *,
        generation: int,
        result: str | None = None,
    ) -> bool: ...

    def schedule_configuration_refresh(
        self, *, delay: float = CONFIGURATION_WRITE_SPACING_SECONDS
    ) -> object: ...

    async def queue_write(self, *args: Any, **kwargs: Any) -> ChargerCommandHandle: ...
