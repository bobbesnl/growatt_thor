"""Shared minimal Home Assistant stand-ins for focused module tests."""

import sys
from types import ModuleType


class HomeAssistantError(Exception):
    def __init__(
        self, *args, translation_domain=None, translation_key=None, translation_placeholders=None
    ):
        super().__init__(*args or (translation_key,))
        self.translation_domain = translation_domain
        self.translation_key = translation_key
        self.translation_placeholders = translation_placeholders


class ServiceValidationError(HomeAssistantError):
    pass


def install_ha_stubs():
    """Provide action exceptions without replacing an existing HA implementation."""
    root = sys.modules.setdefault("homeassistant", ModuleType("homeassistant"))
    exceptions = sys.modules.setdefault(
        "homeassistant.exceptions", ModuleType("homeassistant.exceptions")
    )
    root.exceptions = exceptions
    if not hasattr(exceptions, "HomeAssistantError"):
        exceptions.HomeAssistantError = HomeAssistantError
    if not hasattr(exceptions, "ServiceValidationError"):
        exceptions.ServiceValidationError = ServiceValidationError
