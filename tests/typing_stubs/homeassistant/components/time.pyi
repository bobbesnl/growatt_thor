from datetime import time

from homeassistant.helpers.entity import Entity

class TimeEntity(Entity):
    @property
    def native_value(self) -> time | None: ...
