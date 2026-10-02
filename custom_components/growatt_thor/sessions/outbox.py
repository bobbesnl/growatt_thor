"""Durable handoff of completed sessions from HA storage to CSV."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from copy import deepcopy

# Opaque persisted CSV fields; the outbox owns only the string session identity.
SessionRow = dict[str, object]


class SessionOutbox:
    """Checkpoint before delivery and safely replay an interrupted append."""

    def __init__(self) -> None:
        self._rows: dict[str, SessionRow] = {}
        self._lock = asyncio.Lock()

    def restore(self, rows: object) -> None:
        if isinstance(rows, list):
            for row in rows:
                if (
                    isinstance(row, dict)
                    and isinstance(row.get("session_id"), str)
                    and row["session_id"]
                ):
                    self.enqueue(row)

    def snapshot(self) -> list[SessionRow]:
        return deepcopy(list(self._rows.values()))

    def enqueue(self, row: SessionRow) -> None:
        identity = row.get("session_id")
        if not isinstance(identity, str) or not identity:
            raise ValueError("session_id must be a non-empty string")
        self._rows[identity] = deepcopy(row)

    async def flush(
        self,
        save_checkpoint: Callable[[], Awaitable[None]],
        append_row: Callable[[SessionRow], Awaitable[None]],
    ) -> None:
        async with self._lock:
            if not self._rows:
                return
            # The checkpoint includes both updated totals and pending rows.
            # Persist it first so a crash after CSV append can safely replay delivery.
            await save_checkpoint()
            for identity, row in list(self._rows.items()):
                await append_row(deepcopy(row))
                # enqueue() may replace this session while append_row() is awaited.
                # Acknowledging the older copy must not remove the newer one.
                if self._rows.get(identity) != row:
                    continue
                del self._rows[identity]
                try:
                    await save_checkpoint()
                except BaseException:
                    # Even cancellation can interrupt the acknowledgement save.
                    # Keep a retryable row; CSV delivery deduplicates its session ID.
                    self._rows.setdefault(identity, row)
                    raise
