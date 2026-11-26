from enum import StrEnum

from homeassistant.helpers.entity import Entity

class ButtonDeviceClass(StrEnum):
    RESTART = "restart"

class ButtonEntity(Entity): ...
