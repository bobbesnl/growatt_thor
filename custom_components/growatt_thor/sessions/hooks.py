"""Explicit callbacks for the target controller's observed transaction lifecycle."""

from typing import Protocol


class TransactionHooks(Protocol):
    """Receive charger observations; accepted commands are not observations."""

    def cancel_timer(self) -> None:
        """Cancel this entry's scheduled target timer."""
        ...

    async def transaction_started(self, **kwargs: object) -> None:
        """React to an observed transaction start."""
        ...

    async def transaction_stopped(self, **kwargs: object) -> None:
        """React to an observed transaction stop."""
        ...
