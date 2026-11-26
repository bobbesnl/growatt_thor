"""Per-key generations and outcomes of ChangeConfiguration writes for one charger."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping

from ..coerce import enum_value
from .writes import (
    ConfigurationWriteState,
    ConfigurationWriteStatus,
    acknowledge_configuration_write,
    begin_configuration_write,
    configuration_write_is_current,
    confirm_configuration_writes,
    mark_configuration_write,
)

_LOGGER = logging.getLogger(__name__)


class ConfigurationWriteTracker:
    """Own the write state; the pure transitions live in ``writes.py``.

    ``now`` and ``notify`` are called through the owner at each use, so the
    tracker reports the owner's clock and publishes through the owner.
    """

    def __init__(self, *, now: Callable[[], str], notify: Callable[[], None]) -> None:
        self._now = now
        self._notify = notify
        self.writes: dict[str, ConfigurationWriteState] = {}

    def begin(self, key: str, raw_value: str) -> int:
        """Track a configuration write and return its per-key generation."""
        self.writes = begin_configuration_write(
            self.writes,
            key=key,
            raw_value=raw_value,
            requested_at=self._now(),
        )
        self._notify()
        return self.writes[key].generation

    def is_current(self, key: str, generation: int) -> bool:
        """Return whether a callback still owns the latest intent for a key."""
        return configuration_write_is_current(self.writes, key=key, generation=generation)

    def acknowledge(self, key: str, *, generation: int, accepted: bool, result: object) -> bool:
        """Retain a current OCPP result; ignore a superseded response."""
        # Example: 10 A was sent, then 16 A was requested before its reply.
        # The 10 A acknowledgement is real, but cannot confirm the newer 16 A intent.
        outcome_is_current = self.is_current(key, generation)
        if not outcome_is_current:
            _LOGGER.info(
                "Ignoring superseded ChangeConfiguration result for %s (generation %d)",
                key,
                generation,
            )
        result_value = enum_value(result, stringify_fallback=True)
        self.writes = acknowledge_configuration_write(
            self.writes,
            key=key,
            generation=generation,
            accepted=accepted,
            result=result_value,
        )
        self._notify()
        return outcome_is_current

    def mark(
        self,
        key: str,
        status: ConfigurationWriteStatus,
        *,
        generation: int,
        result: str | None = None,
    ) -> bool:
        """Retain a current non-acknowledgement outcome."""
        outcome_is_current = self.is_current(key, generation)
        if not outcome_is_current:
            _LOGGER.info(
                "Ignoring superseded %s outcome for %s (generation %d)",
                status.value,
                key,
                generation,
            )
        self.writes = mark_configuration_write(
            self.writes,
            key=key,
            generation=generation,
            status=status,
            result=result,
        )
        self._notify()
        return outcome_is_current

    def confirm_readback(self, reported_values: Mapping[str, str | None]) -> bool:
        """Match a GetConfiguration readback; return whether any write changed."""
        confirmed = confirm_configuration_writes(
            self.writes, reported_values, readback_at=self._now()
        )
        if confirmed == self.writes:
            return False
        self.writes = confirmed
        return True
