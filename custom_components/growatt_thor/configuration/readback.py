"""One coalesced GetConfiguration readback after configuration writes."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ..const import CONFIGURATION_WRITE_SPACING_SECONDS
from ..runtime.keys import ACTIVE_CHARGE_POINT

if TYPE_CHECKING:
    from ..coordinator import GrowattCoordinator


class ConfigurationReadback:
    """Own the shared readback task of one charger."""

    def __init__(self, coordinator: GrowattCoordinator, connection_changed: asyncio.Event) -> None:
        self._coordinator = coordinator
        self._connection_changed = connection_changed
        self.task: asyncio.Task[bool] | None = None

    def schedule(self, *, delay: float = CONFIGURATION_WRITE_SPACING_SECONDS) -> asyncio.Task[bool]:
        """Coalesce post-write readbacks into one reconnect-safe task.

        Historically each accepted write slept for exactly the same 20 seconds
        as the queue rate limit.  The readback and the next write therefore woke
        together and competed for the OCPP connection.  A single shared task
        now waits until all queued writes have finished, then reads once from
        whichever connection is current at that time.
        """
        if self.task is not None and not self.task.done():
            return self.task

        self.task = self._coordinator.hass.async_create_task(self._refresh(delay))
        return self.task

    async def _refresh(self, delay: float) -> bool:
        """Wait for a safe request window and refresh reported configuration."""
        try:
            if delay > 0:
                await asyncio.sleep(delay)

            while True:
                await self._coordinator.write_queue.idle.wait()

                charge_point = self._coordinator.runtime_data.get(ACTIVE_CHARGE_POINT)
                if charge_point is None or not self._coordinator.connected:
                    self._connection_changed.clear()
                    charge_point = self._coordinator.runtime_data.get(ACTIVE_CHARGE_POINT)
                    if charge_point is None or not self._coordinator.connected:
                        await self._connection_changed.wait()
                    continue

                # trigger_get_configuration repeats the pending-write check
                # while holding the per-connection request lock.  If a write
                # enters the queue in this small hand-off window, retry after
                # the queue is idle rather than racing it.
                completed = await charge_point.trigger_get_configuration(
                    skip_if_writes_pending=True
                )
                if completed:
                    return True
                # A false result can represent a 30-second timeout, a stale
                # connection, or a newly queued write.  Backing off avoids a
                # tight retry loop while the websocket cleanup catches up.
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            return False
        finally:
            self.task = None
