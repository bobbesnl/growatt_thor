"""Home Assistant schemas and dispatch for native charging targets."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any, cast

import voluptuous as vol
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError

from ..const import DOMAIN
from ..runtime.keys import TARGET_HANDLERS
from ..runtime.ownership import resolve_entry_runtime
from .runtime import (
    SERVICES,
)
from .runtime import (
    async_setup_target_runtime as async_setup_target_services,
)
from .runtime import (
    async_unload_target_runtime as async_unload_target_services,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall

# Entry setup and unload use the runtime functions under their service-facing names.
__all__ = [
    "async_register_target_services",
    "async_setup_target_services",
    "async_unload_target_services",
]

TargetHandler = Callable[["ServiceCall"], Awaitable[Mapping[str, Any] | None]]


def async_register_target_services(hass: HomeAssistant) -> None:
    """Keep action schemas available even when the config entry is unloaded."""

    def dispatch(name: str) -> TargetHandler:
        async def handle(service: ServiceCall) -> Mapping[str, Any] | None:
            try:
                runtime = resolve_entry_runtime(
                    hass.data.get(DOMAIN, {}), service.data.get("entry_id")
                )
            except ValueError as exc:
                raise HomeAssistantError(str(exc)) from exc
            handlers = cast(Mapping[str, TargetHandler], runtime.get(TARGET_HANDLERS, {}))
            handler = handlers.get(name)
            if handler is None:
                raise HomeAssistantError("growatt_thor_entry_not_loaded")
            return await handler(service)

        return handle

    registrations = _target_service_registrations()
    for name, schema, response_options in registrations:
        hass.services.async_register(
            DOMAIN, name, dispatch(name), schema=schema(), **response_options
        )


def _target_schemas() -> tuple[dict[Any, Any], dict[Any, Any], dict[Any, Any]]:
    target_schema = {
        vol.Optional("entry_id"): str,
        vol.Required("kind"): vol.In(["duration", "energy", "budget"]),
        vol.Required("value"): vol.Any(str, int, float),
    }
    confirmed_target_schema = {
        **target_schema,
        vol.Required("confirm_experimental"): vol.All(bool, vol.In([True])),
        vol.Optional("entry_id"): str,
        vol.Optional("replace_request_id"): str,
    }
    prepared_target_schema = {
        vol.Optional("kind", default="energy"): vol.In(["duration", "energy", "budget"]),
        vol.Required("value"): vol.Any(str, int, float),
        vol.Required("confirm_experimental"): vol.All(bool, vol.In([True])),
        vol.Optional("entry_id"): str,
        vol.Optional("replace_request_id"): str,
    }
    return target_schema, confirmed_target_schema, prepared_target_schema


def _target_service_registrations() -> tuple[
    tuple[str, Callable[[], vol.Schema], dict[str, Any]], ...
]:
    target_schema, confirmed_target_schema, prepared_target_schema = _target_schemas()
    return (
        (
            SERVICES[0],
            lambda: vol.Schema(
                {
                    **target_schema,
                    vol.Optional("start", default="now"): vol.In(["now", "once", "recurring"]),
                }
            ),
            {"supports_response": SupportsResponse.ONLY},
        ),
        (
            SERVICES[1],
            lambda: vol.Schema(confirmed_target_schema),
            {"supports_response": SupportsResponse.ONLY},
        ),
        (
            SERVICES[2],
            lambda: vol.Schema(
                {
                    vol.Optional("entry_id"): str,
                    vol.Required("confirm_native_target_reset"): vol.All(bool, vol.In([True])),
                }
            ),
            {},
        ),
        (
            SERVICES[3],
            lambda: vol.Schema(prepared_target_schema),
            {"supports_response": SupportsResponse.ONLY},
        ),
        (
            SERVICES[4],
            lambda: vol.Schema({vol.Optional("entry_id"): str}),
            {"supports_response": SupportsResponse.ONLY},
        ),
        (SERVICES[5], lambda: vol.Schema(prepared_target_schema), {}),
        (
            SERVICES[6],
            lambda: vol.Schema(
                {
                    **prepared_target_schema,
                    vol.Required("entry_id"): str,
                    vol.Required("start_at"): str,
                    vol.Optional("recurrence", default="once"): vol.In(["once", "daily"]),
                }
            ),
            {},
        ),
        (
            SERVICES[7],
            lambda: vol.Schema(
                {
                    vol.Optional("entry_id"): str,
                    vol.Required("request_id"): str,
                    vol.Required("confirm_cancel"): vol.All(bool, vol.In([True])),
                }
            ),
            {},
        ),
    )
