from dataclasses import dataclass
from typing import Any

from homeassistant.helpers.entity import Entity, EntityDescription

BinarySensorDeviceClass: Any

@dataclass(frozen=True, kw_only=True)
class BinarySensorEntityDescription(EntityDescription):
    device_class: Any = ...

class BinarySensorEntity(Entity):
    entity_description: BinarySensorEntityDescription
    @property
    def is_on(self) -> bool | None: ...
