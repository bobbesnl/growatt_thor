"""Session observations reach the declared transaction hook contract."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests.support import build_coordinator


class TransactionHooksTest(unittest.IsolatedAsyncioTestCase):
    async def test_start_and_stop_publish_the_observed_transaction_identity(self):
        coordinator = build_coordinator()
        coordinator.now = lambda: "2026-10-30T12:00:00Z"
        hooks = SimpleNamespace(transaction_started=AsyncMock(), transaction_stopped=AsyncMock())
        coordinator.transaction_hooks = hooks
        tasks = []

        def schedule(coroutine):
            task = asyncio.create_task(coroutine)
            tasks.append(task)
            return task

        coordinator.hass.async_create_task = schedule
        coordinator.start_transaction(42, connector_id=1)
        await asyncio.gather(*tasks)
        hooks.transaction_started.assert_awaited_once_with(transaction_id=42)
        hooks.transaction_stopped.assert_not_called()
        tasks.clear()
        coordinator.stop_transaction(transaction_id=42, reason="Local")
        await asyncio.gather(*tasks)
        hooks.transaction_stopped.assert_awaited_once_with(transaction_id=42, reason="Local")
