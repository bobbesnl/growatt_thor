from typing import Any

from homeassistant.helpers.entity import Entity

NumberDeviceClass: Any
NumberMode: Any

class NumberEntity(Entity):
    _attr_native_min_value: float
    _attr_native_max_value: float
    _attr_native_step: float
    _attr_native_unit_of_measurement: str | None
    _attr_suggested_display_precision: int | None
    _attr_device_class: Any
    _attr_mode: Any
    @property
    def native_value(self) -> float | None: ...
    @property
    def native_min_value(self) -> float: ...
    @property
    def native_max_value(self) -> float: ...
    @property
    def native_step(self) -> float: ...
    @property
    def native_unit_of_measurement(self) -> str | None: ...
