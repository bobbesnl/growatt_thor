"""Explicit callbacks for the target controller's observed transaction lifecycle."""

from typing import Protocol

from .goal import SessionGoal


class TransactionHooks(Protocol):
    """Receive charger observations; accepted commands are not observations."""

    def cancel_timer(self) -> None:
        """Cancel this entry's scheduled target timer."""
        ...

    def session_goal_for_start(self) -> SessionGoal | None:
        """Snapshot a confirmed target when an actual session starts."""
        ...

    async def transaction_started(self, *, transaction_id: object = None) -> None:
        """React to an observed transaction start."""
        ...

    async def transaction_stopped(self, **kwargs: object) -> None:
        """React to an observed transaction stop."""
        ...
