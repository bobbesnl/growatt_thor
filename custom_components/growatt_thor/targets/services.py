"""Home Assistant schemas and dispatch for native charging targets."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError

from ..const import DOMAIN
from .runtime import (
    SERVICES,
    async_setup_target_runtime as async_setup_target_services,
    async_unload_target_runtime as async_unload_target_services,
)


if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall

TargetHandler = Callable[["ServiceCall"], Awaitable[dict[str, Any] | None]]


def async_register_target_services(hass: HomeAssistant) -> None:
    """Keep action schemas available even when the config entry is unloaded."""

    def dispatch(name: str) -> TargetHandler:
        async def handle(service: ServiceCall) -> dict[str, Any] | None:
            handler = hass.data.get(DOMAIN, {}).get("target_handlers", {}).get(name)
            if handler is None:
                raise HomeAssistantError("growatt_thor_entry_not_loaded")
            return await handler(service)

        return handle

    target_schema = {
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
        vol.Optional("kind", default="energy"): vol.In(
            ["duration", "energy", "budget"]
        ),
        vol.Required("value"): vol.Any(str, int, float),
        vol.Required("confirm_experimental"): vol.All(bool, vol.In([True])),
        vol.Optional("entry_id"): str,
        vol.Optional("replace_request_id"): str,
    }
    hass.services.async_register(
        DOMAIN,
        SERVICES[0],
        dispatch(SERVICES[0]),
        schema=vol.Schema(
            {
                **target_schema,
                vol.Optional("start", default="now"): vol.In(
                    ["now", "once", "recurring"]
                ),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICES[1],
        dispatch(SERVICES[1]),
        schema=vol.Schema(confirmed_target_schema),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICES[2],
        dispatch(SERVICES[2]),
        schema=vol.Schema(
            {vol.Required("confirm_native_target_reset"): vol.All(bool, vol.In([True]))}
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICES[3],
        dispatch(SERVICES[3]),
        schema=vol.Schema(prepared_target_schema),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICES[4],
        dispatch(SERVICES[4]),
        schema=vol.Schema({}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICES[5],
        dispatch(SERVICES[5]),
        schema=vol.Schema(prepared_target_schema),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICES[6],
        dispatch(SERVICES[6]),
        schema=vol.Schema(
            {
                **prepared_target_schema,
                vol.Required("entry_id"): str,
                vol.Required("start_at"): str,
                vol.Optional("recurrence", default="once"): vol.In(["once", "daily"]),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICES[7],
        dispatch(SERVICES[7]),
        schema=vol.Schema(
            {
                vol.Required("request_id"): str,
                vol.Required("confirm_cancel"): vol.All(bool, vol.In([True])),
            }
        ),
    )


