"""Home Assistant errors for charger action validation and completion.

Entity methods are also Home Assistant service-action handlers. Logging and
returning from such a method tells scripts and automations that the action
succeeded, even when no charger command was queued or confirmed. These helpers
keep both boundaries explicit and ensure every caller uses the same translated
error.
"""
from __future__ import annotations

from collections.abc import Mapping

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import DOMAIN
from .write_queue import (
    ChargerCommandHandle,
    ChargerCommandResult,
    ChargerCommandStatus,
    ChargerCommandWaitTimeout,
)


DEFAULT_ACTION_COMMAND_WAIT_TIMEOUT = 30.0


# A disconnected charger is a communication failure. The remaining reasons
# describe a request that is invalid in the current charger/configuration state
# and should therefore be reported as a validation error without a noisy stack
# trace in normal Home Assistant logs.
_WRITE_BLOCK_TRANSLATIONS: Mapping[str, tuple[type[HomeAssistantError], str]] = {
    "charger_disconnected": (HomeAssistantError, "charger_disconnected"),
    "charger_faulted": (ServiceValidationError, "charger_faulted"),
    "active_transaction": (ServiceValidationError, "active_transaction"),
    "control_not_applicable": (
        ServiceValidationError,
        "control_not_applicable",
    ),
    "configuration_read_only": (
        ServiceValidationError,
        "configuration_read_only",
    ),
}


def raise_write_blocked(reason: str) -> None:
    """Raise the HA exception matching one stable internal block reason."""
    exception_type, translation_key = _WRITE_BLOCK_TRANSLATIONS.get(
        reason,
        (ServiceValidationError, "action_not_allowed"),
    )
    placeholders = None if translation_key != "action_not_allowed" else {
        "reason": reason,
    }
    raise exception_type(
        translation_domain=DOMAIN,
        translation_key=translation_key,
        translation_placeholders=placeholders,
    )


def raise_charger_disconnected() -> None:
    """Report a stale or missing runtime connection to Home Assistant."""
    raise_write_blocked("charger_disconnected")


def raise_action_validation(
    translation_key: str,
    *,
    placeholders: Mapping[str, object] | None = None,
) -> None:
    """Reject a user action using a known integration translation key."""
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=translation_key,
        translation_placeholders=_stringify_placeholders(placeholders),
    )


def raise_communication_error(
    translation_key: str,
    *,
    placeholders: Mapping[str, object] | None = None,
) -> None:
    """Report a runtime service failure to the calling HA automation."""
    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=translation_key,
        translation_placeholders=_stringify_placeholders(placeholders),
    )


async def async_require_command_completion(
    handle: ChargerCommandHandle,
    *,
    timeout: float = DEFAULT_ACTION_COMMAND_WAIT_TIMEOUT,
) -> ChargerCommandResult:
    """Wait a bounded time and turn non-confirmation into an HA action error.

    The underlying queue command keeps running if the wait times out or the HA
    caller is cancelled.  This prevents a dashboard timeout from being
    mistaken for proof that the charger never received the request.
    """
    try:
        result = await handle.async_wait(timeout=timeout)
    except ChargerCommandWaitTimeout:
        raise_communication_error(
            "command_still_pending",
            placeholders={"command_id": handle.command_id},
        )

    if result.status == ChargerCommandStatus.CONFIRMED:
        return result

    details = result.reason or result.charger_result or "unknown"
    placeholders = {
        "command_id": result.command_id,
        "command_name": result.command_name,
        "status": result.status.value,
        "details": details,
    }
    if result.status in {
        ChargerCommandStatus.SKIPPED,
        ChargerCommandStatus.EXPIRED,
    }:
        raise_action_validation(
            "command_not_executed",
            placeholders=placeholders,
        )
    if result.status == ChargerCommandStatus.UNCERTAIN:
        raise_communication_error(
            "command_outcome_uncertain",
            placeholders=placeholders,
        )
    raise_communication_error(
        "command_failed",
        placeholders=placeholders,
    )


def _stringify_placeholders(
    placeholders: Mapping[str, object] | None,
) -> dict[str, str] | None:
    """Normalize translated error placeholders in one shared boundary."""
    if placeholders is None:
        return None
    return {key: str(value) for key, value in placeholders.items()}
