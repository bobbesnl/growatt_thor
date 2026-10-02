"""OCPP connection liveness tracking."""
from __future__ import annotations

from dataclasses import dataclass


OCPP_HEARTBEAT_INTERVAL_SECONDS = 60
MISSED_ACTIVITY_LIMIT = 3
CONNECTION_ACTIVITY_TIMEOUT_SECONDS = (
    OCPP_HEARTBEAT_INTERVAL_SECONDS * MISSED_ACTIVITY_LIMIT
)
CONNECTION_WATCHDOG_INTERVAL_SECONDS = 15


@dataclass
class OcppConnectionActivity:
    """Track the latest inbound OCPP activity using monotonic time."""

    last_message_monotonic: float
    timeout_seconds: float = CONNECTION_ACTIVITY_TIMEOUT_SECONDS

    def mark(self, now_monotonic: float) -> None:
        """Record inbound OCPP activity."""
        self.last_message_monotonic = now_monotonic

    def idle_seconds(self, now_monotonic: float) -> float:
        """Return elapsed time since the last inbound OCPP message."""
        return max(0.0, now_monotonic - self.last_message_monotonic)

    def is_stale(self, now_monotonic: float) -> bool:
        """Return whether the connection exceeded the activity timeout."""
        return self.idle_seconds(now_monotonic) >= self.timeout_seconds
