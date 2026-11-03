"""A ChargerControl stand-in that records requests instead of queueing writes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StopRequest:
    """One recorded ``async_stop`` call."""

    auto_guard: Callable[[], str | None] | None
    stop_reason: str | None
    on_result: Callable[[Any], None] | None


@dataclass
class FakeChargerControl:
    """Callers of ChargerControl can be tested without a coordinator or queue.

    ``start_block_reason`` is reported as is; ``error`` is raised by every
    request after it was recorded; ``stop_result`` is handed to ``on_result``
    like a terminal queue result.
    """

    start_block_reason: str | None = None
    error: BaseException | None = None
    stop_result: Any = None
    starts: int = 0
    stops: list[StopRequest] = field(default_factory=list)

    async def async_start(self) -> None:
        self.starts += 1
        if self.error is not None:
            raise self.error

    async def async_stop(
        self,
        *,
        auto_guard: Callable[[], str | None] | None = None,
        stop_reason: str | None = None,
        on_result: Callable[[Any], None] | None = None,
    ) -> None:
        self.stops.append(StopRequest(auto_guard, stop_reason, on_result))
        if self.error is not None:
            raise self.error
        if on_result is not None and self.stop_result is not None:
            on_result(self.stop_result)
