from homeassistant.helpers.entity import Entity

class SelectEntity(Entity):
    _attr_options: list[str]
    @property
    def options(self) -> list[str]: ...
