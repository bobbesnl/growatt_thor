"""Pure decisions shared by the Remote Start and Stop controls.

Keeping these rules independent of Home Assistant entities makes the unusual
automation edge cases explicit and cheap to regression-test.  The queue still
performs the final check immediately before an OCPP request is sent.
"""
from __future__ import annotations

from typing import Final


REMOTE_START_COMMAND: Final = "RemoteStartTransaction"
REMOTE_STOP_COMMAND: Final = "RemoteStopTransaction"

# Start and Stop are two directions of one logical control.  Sharing a queue
# key prevents delayed opposing commands from surviving as independent work.
SESSION_CONTROL_DEDUPE_KEY: Final = "charging_session_control"
STOP_CANCELLED_START_REASON: Final = "cancelled_by_stop_intent"


def start_revalidation_failure(
    *,
    charger_faulted: bool,
    transaction_active: bool,
) -> str | None:
    """Return why a Remote Start intent is no longer safe to send."""
    if charger_faulted:
        return "charger_faulted"
    if transaction_active:
        return "charging_already_active"
    return None


def stop_revalidation_failure(
    *,
    expected_transaction_id: int,
    current_transaction_id: object,
    transaction_active: bool,
) -> str | None:
    """Return why a Remote Stop no longer targets its original session.

    An exact transaction-ID match is deliberately required.  A later session
    must never inherit a Stop that was queued for an earlier one, even when a
    reconnect delayed delivery of the command.
    """
    if current_transaction_id != expected_transaction_id:
        return (
            "transaction_ended"
            if current_transaction_id is None
            else "transaction_changed"
        )
    if not transaction_active:
        return "transaction_ended"
    return None
