"""Minimal HA base for checking concrete owner contracts without importing HA.

An unresolved base class behaves as Any and hides missing coordinator members.
This stub covers only the inherited capabilities used by GrowattCoordinator.
"""

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .entity import Entity

class DataUpdateCoordinator[T]:
    hass: HomeAssistant
    last_update_success: bool
    data: T | None
    def __init__(
        self, hass: HomeAssistant, logger: logging.Logger, *, name: str, **kwargs: Any
    ) -> None: ...
    def async_set_updated_data(self, data: T) -> None: ...

class CoordinatorEntity[T](Entity):
    coordinator: T
    def __init__(self, coordinator: T, *args: Any, **kwargs: Any) -> None: ...
