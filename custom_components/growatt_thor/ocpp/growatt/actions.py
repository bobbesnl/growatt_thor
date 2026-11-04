"""Response timeout and retry policy for every OCPP action the integration sends.

The values were chosen per call site for the THOR firmware; this table keeps
them in one place. Call sites read their policy from here instead of repeating
literals, so a changed timeout or uncertainty rule shows up in one diff.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..core.connection import (
    CONFIGURATION_REFRESH_WAIT_SECONDS,
    CONFIGURATION_REQUEST_TIMEOUT_SECONDS,
)

# The ocpp library's ChargePoint default; GrowattChargePoint passes it explicitly.
OCPP_RESPONSE_TIMEOUT_SECONDS = 30


class OcppRetry(StrEnum):
    """What happens after a request fails or times out."""

    #: Never resent automatically. The write queue or the target runner owns
    #: the outcome, and an unknown outcome stays uncertain until readback.
    NONE = "none"
    #: Read again on the next polling or command cycle.
    NEXT_POLL = "next_poll"
    #: Read again on the next poll; repeated timeouts pause polling with a
    #: growing backoff because the THOR is likely rebooting.
    BACKOFF = "backoff"
    #: Read again after the next connection.
    RECONNECT = "reconnect"


@dataclass(frozen=True, slots=True)
class OcppActionPolicy:
    """How long to wait for one action and how to treat a missing answer."""

    #: Seconds to wait for the CALLRESULT of one CALL.
    response_timeout: float
    #: True when the charger may have acted although no answer arrived: the
    #: request reached the wire, so a timeout reports an uncertain outcome
    #: instead of a definite failure.
    timeout_makes_outcome_uncertain: bool
    retry: OcppRetry


OCPP_ACTIONS: dict[str, OcppActionPolicy] = {
    # Reads. A lost answer changes nothing on the charger.
    "TriggerMessage(StatusNotification)": OcppActionPolicy(
        OCPP_RESPONSE_TIMEOUT_SECONDS, False, OcppRetry.NEXT_POLL
    ),
    "TriggerMessage(BootNotification)": OcppActionPolicy(
        OCPP_RESPONSE_TIMEOUT_SECONDS, False, OcppRetry.RECONNECT
    ),
    # Each of the two firmware-sized groups gets its own bound; the second
    # (diagnostic) group may time out without discarding the first.
    "GetConfiguration": OcppActionPolicy(
        CONFIGURATION_REQUEST_TIMEOUT_SECONDS, False, OcppRetry.RECONNECT
    ),
    "DataTransfer(get_external_meterval)": OcppActionPolicy(
        CONFIGURATION_REFRESH_WAIT_SECONDS, False, OcppRetry.BACKOFF
    ),
    # Writes and commands. Each reaches the queue as one attempt.
    "ChangeConfiguration": OcppActionPolicy(OCPP_RESPONSE_TIMEOUT_SECONDS, True, OcppRetry.NONE),
    "DataTransfer": OcppActionPolicy(OCPP_RESPONSE_TIMEOUT_SECONDS, True, OcppRetry.NONE),
    "RemoteStartTransaction": OcppActionPolicy(OCPP_RESPONSE_TIMEOUT_SECONDS, True, OcppRetry.NONE),
    "RemoteStopTransaction": OcppActionPolicy(OCPP_RESPONSE_TIMEOUT_SECONDS, True, OcppRetry.NONE),
    # Target operations call the library directly inside the target runner,
    # which classifies their failures itself.
    "ReserveNow": OcppActionPolicy(OCPP_RESPONSE_TIMEOUT_SECONDS, True, OcppRetry.NONE),
    "CancelReservation": OcppActionPolicy(OCPP_RESPONSE_TIMEOUT_SECONDS, True, OcppRetry.NONE),
}
