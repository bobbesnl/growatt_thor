from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from homeassistant.helpers.entity import Entity, EntityDescription

SensorDeviceClass: Any
SensorStateClass: Any

@dataclass(frozen=True, kw_only=True)
class SensorEntityDescription(EntityDescription):
    device_class: Any = ...
    state_class: Any = ...
    native_unit_of_measurement: str | None = ...
    suggested_display_precision: int | None = ...
    options: list[str] | None = ...

class SensorEntity(Entity):
    entity_description: SensorEntityDescription
    _attr_device_class: Any
    _attr_state_class: Any
    _attr_native_unit_of_measurement: str | None
    _attr_suggested_display_precision: int | None
    _attr_options: Sequence[str]
    @property
    def native_unit_of_measurement(self) -> str | None: ...
