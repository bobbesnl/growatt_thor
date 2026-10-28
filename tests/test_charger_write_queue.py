"""Queue lifecycle exercised directly without a coordinator or HA entity stand-ins."""

import asyncio
import importlib
import types
import unittest
from unittest.mock import AsyncMock

from support import register_package

package = register_package("thor_queue_owner_test")
queue_module = importlib.import_module(package.__name__ + ".runtime.charger_write_queue")
results = importlib.import_module(package.__name__ + ".runtime.write_results")


class Owner:
    def __init__(self):
        self.hass = types.SimpleNamespace(
            loop=asyncio.get_running_loop(), async_create_task=asyncio.create_task
        )
        self.runtime_data = {}
        self.connected = True
        self.published = []
        self.pause_polling_until = lambda until: None
        self.mark_configuration_write = lambda *args, **kwargs: None
        self.schedule_configuration_refresh = lambda **kwargs: None

    def now(self):
        return "2026-10-25T10:00:00Z"

    def publish_write_result(self, result):
        self.published.append(result)


def make_queue():
    owner = Owner()
    queue = queue_module.ChargerWriteQueue(owner, asyncio.Event())
    queue.min_write_interval = 0
    queue.poll_pause_after_write = 0
    return owner, queue


class ChargerWriteQueueTest(unittest.IsolatedAsyncioTestCase):
    async def test_typed_pending_entries_and_runtime_are_isolated_per_owner(self):
        left_owner, left = make_queue()
        right_owner, right = make_queue()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def hold():
            entered.set()
            await release.wait()
            return results.ChargerWriteResult.success()

        await left.enqueue(hold)
        await entered.wait()
        pending = await left.enqueue(hold)
        self.assertIsInstance(left._pending[0], queue_module.ChargerWriteItem)
        self.assertTrue(left.has_pending)
        self.assertFalse(right.has_pending)
        self.assertTrue(right.idle.is_set())
        callback = AsyncMock(return_value=results.ChargerWriteResult.success("Accepted"))
        done = await right.enqueue(callback, command_name="Independent")
        self.assertEqual(
            (await done.async_wait(timeout=0.2)).status,
            results.ChargerCommandStatus.CONFIRMED,
        )
        self.assertEqual(len(right_owner.published), 1)
        self.assertEqual(left_owner.published, [])
        release.set()
        await pending.async_wait(timeout=0.2)
        await left.async_shutdown()
        await right.async_shutdown()

    async def test_shutdown_distinguishes_active_from_unsent_and_notifies_once(self):
        owner, queue = make_queue()
        entered = asyncio.Event()
        cleanup = []
        completed = []

        async def active():
            entered.set()
            await asyncio.Event().wait()

        running = await queue.enqueue(active)
        await entered.wait()
        never_sent = AsyncMock()
        waiting = await queue.enqueue(
            never_sent,
            command_name="Pending",
            on_unsent=lambda result: cleanup.append(result.status),
        )
        waiting.add_done_callback(lambda result: completed.append(result.status))
        await queue.async_shutdown()
        await queue.async_shutdown()
        await asyncio.sleep(0)
        self.assertEqual(
            (await running.async_wait(timeout=0.2)).status,
            results.ChargerCommandStatus.UNCERTAIN,
        )
        self.assertEqual(
            (await waiting.async_wait(timeout=0.2)).status,
            results.ChargerCommandStatus.SKIPPED,
        )
        self.assertEqual(cleanup, [results.ChargerWriteStatus.SKIPPED])
        self.assertEqual(completed, [results.ChargerCommandStatus.SKIPPED])
        self.assertEqual(len(owner.published), 2)
        never_sent.assert_not_awaited()
        self.assertFalse(queue.has_pending)
        self.assertTrue(queue.idle.is_set())

    async def test_publication_failure_does_not_strand_completion_or_later_work(self):
        owner, queue = make_queue()

        def publish(result):
            owner.published.append(result)
            raise RuntimeError("listener failed")

        owner.publish_write_result = publish
        write = AsyncMock(return_value=results.ChargerWriteResult.success())
        with self.assertLogs(queue_module._LOGGER, level="ERROR"):
            first = await queue.enqueue(write, command_name="First")
            second = await queue.enqueue(write, command_name="Second")
            self.assertEqual(
                (await first.async_wait(timeout=0.2)).status,
                results.ChargerCommandStatus.CONFIRMED,
            )
            self.assertEqual(
                (await second.async_wait(timeout=0.2)).status,
                results.ChargerCommandStatus.CONFIRMED,
            )
        self.assertEqual(queue.last_result.command_id, second.command_id)
        self.assertEqual(len(owner.published), 2)
        await queue.async_shutdown()

    async def test_closed_queue_resolves_late_work_without_executing(self):
        owner, queue = make_queue()
        await queue.async_shutdown()
        write = AsyncMock()
        handle = await queue.enqueue(write, command_name="Late")
        result = await handle.async_wait(timeout=0.2)
        self.assertEqual(result.reason, "integration_unloaded")
        self.assertEqual(result.status, results.ChargerCommandStatus.SKIPPED)
        write.assert_not_awaited()
        self.assertTrue(queue.idle.is_set())
