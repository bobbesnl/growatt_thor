"""Short-lived, per-wallbox capture of one explicitly requested RFID swipe."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import monotonic

LEARNING_SECONDS = 120


@dataclass(eq=False)
class LearningSession:
    expires_at: float
    id_tag: str | None = field(default=None, repr=False)


class RfidLearning:
    """Capture an identifier without changing the authorization decision."""

    def __init__(self):
        self._session: LearningSession | None = None
        self._timer: asyncio.TimerHandle | None = None

    def _expire(self):
        if self._session is not None and monotonic() >= self._session.expires_at:
            self.cancel(self._session)

    def begin(self) -> LearningSession:
        self._expire()
        if self._session is not None:
            raise ValueError("rfid_learning_busy")
        session = LearningSession(monotonic() + LEARNING_SECONDS)
        self._timer = asyncio.get_running_loop().call_later(
            LEARNING_SECONDS,
            self.cancel,
            session,
        )
        self._session = session
        return session

    def capture(self, id_tag: str) -> None:
        self._expire()
        if self._session is not None and self._session.id_tag is None:
            self._session.id_tag = id_tag

    def identifier(self, session: LearningSession) -> str | None:
        self._expire()
        if session is not self._session:
            raise ValueError("rfid_learning_expired")
        return session.id_tag

    def cancel(self, session: LearningSession) -> None:
        # An old dialog must never clear a newer dialog's capture.
        if session is self._session:
            session.id_tag = None
            self._session = None
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
