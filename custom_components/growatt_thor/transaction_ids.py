"""Local OCPP transaction ID allocation."""
from __future__ import annotations

from typing import Any


MIN_TRANSACTION_ID = 1


def normalize_next_transaction_id(value: Any) -> int:
    """Return a valid positive next transaction ID."""
    try:
        transaction_id = int(value)
    except (TypeError, ValueError):
        return MIN_TRANSACTION_ID
    return max(transaction_id, MIN_TRANSACTION_ID)


class TransactionIdAllocator:
    """Allocate monotonically increasing IDs from persisted state."""

    def __init__(self, next_transaction_id: Any = MIN_TRANSACTION_ID):
        self._next_transaction_id = normalize_next_transaction_id(
            next_transaction_id
        )

    @property
    def next_transaction_id(self) -> int:
        """Return the value that will be allocated next."""
        return self._next_transaction_id

    def restore(self, next_transaction_id: Any) -> None:
        """Restore the next value from Home Assistant storage."""
        self._next_transaction_id = normalize_next_transaction_id(
            next_transaction_id
        )

    def allocate(self) -> int:
        """Return one ID and advance the allocator."""
        transaction_id = self._next_transaction_id
        self._next_transaction_id += 1
        return transaction_id
