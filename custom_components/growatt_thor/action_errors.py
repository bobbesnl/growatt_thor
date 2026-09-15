"""Home Assistant errors for charger actions rejected before queueing.

Entity methods are also Home Assistant service-action handlers. Logging and
returning from such a method tells scripts and automations that the action
succeeded, even when no charger command was queued. These helpers keep that
boundary explicit and ensure every caller uses the same translated error.
"""
from __future__ import annotations

from collections.abc import Mapping

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import DOMAIN


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
        translation_placeholders=(
            None
            if placeholders is None
            else {key: str(value) for key, value in placeholders.items()}
        ),
    )
