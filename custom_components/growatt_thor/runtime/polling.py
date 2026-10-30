"""Wakeable polling cadence used by live config-entry options."""

from __future__ import annotations

import asyncio
import logging

from .keys import ACTIVE_CHARGE_POINT, COORDINATOR, SKIP_POLLING_UNTIL

_LOGGER = logging.getLogger(__name__)


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
            except TimeoutError:
                # Do not consume a revision that raced with the timeout.
                if self._revision != revision:
                    continue
                self._consumed_revision = revision
                return
            # An options update woke us. Loop so the next cycle is scheduled
            # from the update moment using the newly published interval.
            continue


class ExternalMeterPoller:
    """Own polling cadence and the one-entry pause log state."""

    def __init__(self, runtime, schedule: PollIntervalSchedule) -> None:
        self.runtime = runtime
        self.schedule = schedule
        self._skip_logged = False

    async def run(self) -> None:
        loop = asyncio.get_event_loop()
        poll_started = False

        while True:
            # The schedule can be woken by the options flow.  This makes a new
            # interval effective for the very next cycle instead of leaving a
            # stale sleep (or requiring an integration reload).
            await self.schedule.async_wait_for_next_cycle()
            poll_interval = self.schedule.interval
            if not poll_started:
                _LOGGER.info(
                    "External meter poll started (interval: %ds)",
                    poll_interval,
                )
                poll_started = True
            try:
                skip_until = self.runtime.get(SKIP_POLLING_UNTIL, 0.0)
                current_time = loop.time()

                while current_time < skip_until:
                    if not self._skip_logged:
                        remaining = int(skip_until - current_time)
                        _LOGGER.info("Polling paused (%ds remaining)", remaining)
                        self._skip_logged = True
                    await asyncio.sleep(min(1, skip_until - current_time))
                    current_time = loop.time()
                self._skip_logged = False

                charge_point = self.runtime.get(ACTIVE_CHARGE_POINT)
                coordinator = self.runtime.get(COORDINATOR)

                if charge_point and coordinator:
                    _LOGGER.debug("Polling external meter (%ds interval)", poll_interval)
                    # Meter data is periodic and may be skipped once.  It must
                    # never queue behind or wake together with a configuration
                    # write, because the THOR firmware is sensitive to bursts
                    # of integration-initiated requests.
                    await charge_point.trigger_external_meterval(skip_if_writes_pending=True)
                else:
                    _LOGGER.debug("External meter poll skipped: charger not connected")

            except Exception as exc:
                _LOGGER.error("Smart poll crashed: %s", exc, exc_info=True)
