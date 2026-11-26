"""Config-entry identity, typed runtime and flow handlers used at HA setup boundaries."""

from collections.abc import Mapping
from typing import Any, Generic

from typing_extensions import TypeVar

T = TypeVar("T", default=Any)

class ConfigEntry(Generic[T]):
    entry_id: str
    title: str
    version: int
    data: Mapping[str, Any]
    options: Mapping[str, Any]
    runtime_data: T

# HA defines the result as a TypedDict; flow handlers only pass it through.
ConfigFlowResult = dict[str, Any]

class _FlowHandler:
    hass: Any
    def async_show_form(
        self,
        *,
        step_id: str,
        data_schema: Any = None,
        errors: Mapping[str, str] | None = None,
        description_placeholders: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> ConfigFlowResult: ...
    def async_show_menu(
        self, *, step_id: str, menu_options: list[str], **kwargs: Any
    ) -> ConfigFlowResult: ...
    def async_create_entry(
        self, *, title: str, data: Mapping[str, Any], **kwargs: Any
    ) -> ConfigFlowResult: ...
    def async_abort(self, *, reason: str, **kwargs: Any) -> ConfigFlowResult: ...

class ConfigFlow(_FlowHandler):
    VERSION: int
    def __init_subclass__(cls, *, domain: str | None = None, **kwargs: Any) -> None: ...
    def _async_current_entries(self, include_ignore: bool | None = None) -> list[ConfigEntry]: ...

class OptionsFlow(_FlowHandler):
    @property
    def config_entry(self) -> ConfigEntry: ...
