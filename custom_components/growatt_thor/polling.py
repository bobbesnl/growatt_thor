"""Wakeable polling cadence used by live config-entry options."""
from __future__ import annotations

import asyncio


class PollIntervalSchedule:
    """Wait for the current interval and restart timing after an update."""

    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._changed = asyncio.Event()
        self._revision = 0
        self._consumed_revision = 0
        self._updated_at: float | None = None

    @property
    def interval(self) -> float:
        return self._interval

    def update(self, interval: float) -> None:
        """Publish a new interval and wake the current sleep immediately."""
        self._interval = interval
        self._revision += 1
        self._updated_at = asyncio.get_running_loop().time()
        self._changed.set()

    async def async_wait_for_next_cycle(self) -> None:
        """Wait one full interval measured from the most recent update."""
        loop = asyncio.get_running_loop()
        while True:
            revision = self._revision
            # An update may arrive while OCPP work is in progress rather than
            # while this coroutine is asleep.  Retaining its timestamp avoids
            # silently discarding that update at the next ``clear()``.
            if revision != self._consumed_revision:
                assert self._updated_at is not None
                started_at = self._updated_at
            else:
                started_at = loop.time()
            timeout = max(0, started_at + self._interval - loop.time())
            self._changed.clear()
            if self._revision != revision:
                continue
            try:
                await asyncio.wait_for(
                    self._changed.wait(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                # Do not consume a revision that raced with the timeout.
                if self._revision != revision:
                    continue
                self._consumed_revision = revision
                return
            # An options update woke us. Loop so the next cycle is scheduled
            # from the update moment using the newly published interval.
            continue
