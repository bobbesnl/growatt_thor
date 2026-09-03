"""Tests for persistent local OCPP transaction ID allocation."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
    / "transaction_ids.py"
)
SPEC = importlib.util.spec_from_file_location(
    "growatt_thor_transaction_ids_test_target",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
transaction_ids = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = transaction_ids
SPEC.loader.exec_module(transaction_ids)


class TransactionIdAllocatorTest(unittest.TestCase):
    """Verify monotonic allocation and defensive storage restoration."""

    def test_allocates_monotonically_from_default(self):
        allocator = transaction_ids.TransactionIdAllocator()

        self.assertEqual(allocator.allocate(), 1)
        self.assertEqual(allocator.allocate(), 2)
        self.assertEqual(allocator.next_transaction_id, 3)

    def test_restores_persisted_next_value(self):
        allocator = transaction_ids.TransactionIdAllocator()
        allocator.restore("1622130")

        self.assertEqual(allocator.allocate(), 1622130)
        self.assertEqual(allocator.next_transaction_id, 1622131)

    def test_invalid_or_non_positive_storage_value_starts_at_one(self):
        for value in (None, "invalid", 0, -10):
            with self.subTest(value=value):
                allocator = transaction_ids.TransactionIdAllocator(value)
                self.assertEqual(allocator.allocate(), 1)


if __name__ == "__main__":
    unittest.main()
