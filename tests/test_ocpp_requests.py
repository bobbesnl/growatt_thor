"""Regression tests for the application-level OCPP request gate."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest


PACKAGE_PATH = Path(__file__).parents[1] / "custom_components" / "growatt_thor"
PACKAGE_NAME = "growatt_thor_request_test_target"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(PACKAGE_PATH)]
sys.modules[PACKAGE_NAME] = package


def _load_module(name: str):
    path = PACKAGE_PATH / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{PACKAGE_NAME}.{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


write_queue = _load_module("write_queue")
requests = _load_module("ocpp_requests")


class TransportClosed(RuntimeError):
    """Test substitute for a websockets ConnectionClosed exception."""


class OcppRequestGateTest(unittest.IsolatedAsyncioTestCase):
    """Verify serialization, priority rechecks, and retry safety."""

    def setUp(self):
        self.current = True
        self.connected = True
        self.write_pending = False
        self.gate = requests.SerializedOcppRequestGate(
            connection_is_current=lambda: self.current,
            connection_is_available=lambda: self.connected,
            writes_are_pending=lambda: self.write_pending,
            uncertain_transport_errors=(TransportClosed,),
        )

    async def test_logical_operations_do_not_overlap(self):
        """A second operation waits until the first one completely finishes."""
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        second_started = asyncio.Event()
        order = []

        async def first():
            order.append("first_started")
            first_started.set()
            await release_first.wait()
            order.append("first_finished")
            return "first"

        async def second():
            order.append("second_started")
            second_started.set()
            return "second"

        first_task = asyncio.create_task(self.gate.run("first", first))
        await first_started.wait()
        second_task = asyncio.create_task(self.gate.run("second", second))
        await asyncio.sleep(0)

        self.assertFalse(second_started.is_set())
        release_first.set()
        self.assertEqual(await asyncio.gather(first_task, second_task), ["first", "second"])
        self.assertEqual(order, ["first_started", "first_finished", "second_started"])

    async def test_optional_read_is_skipped_before_waiting_for_lock(self):
        self.write_pending = True
        operation_called = False

        async def optional_read():
            nonlocal operation_called
            operation_called = True

        result = await self.gate.run(
            "optional read",
            optional_read,
            skip_if_writes_pending=True,
        )

        self.assertIs(result, requests.REQUEST_SKIPPED)
        self.assertFalse(operation_called)

    async def test_optional_read_rechecks_priority_after_lock_wait(self):
        """A user write queued during the wait wins over an older poll."""
        blocker_started = asyncio.Event()
        release_blocker = asyncio.Event()
        optional_read_called = False

        async def blocker():
            blocker_started.set()
            await release_blocker.wait()

        async def optional_read():
            nonlocal optional_read_called
            optional_read_called = True

        blocker_task = asyncio.create_task(self.gate.run("blocker", blocker))
        await blocker_started.wait()
        read_task = asyncio.create_task(
            self.gate.run(
                "optional read",
                optional_read,
                skip_if_writes_pending=True,
            )
        )
        await asyncio.sleep(0)
        self.write_pending = True
        release_blocker.set()

        await blocker_task
        self.assertIs(await read_task, requests.REQUEST_SKIPPED)
        self.assertFalse(optional_read_called)

    async def test_stale_connection_is_retryable_because_operation_never_started(self):
        self.current = False
        operation_called = False

        async def write():
            nonlocal operation_called
            operation_called = True

        with self.assertRaises(write_queue.ChargerConnectionUnavailable):
            await self.gate.run("write", write)

        self.assertFalse(operation_called)

    async def test_transport_loss_after_handoff_has_uncertain_outcome(self):
        async def write():
            raise TransportClosed("socket closed")

        with self.assertRaises(write_queue.ChargerRequestOutcomeUncertain):
            await self.gate.run("write", write)

    async def test_write_timeout_is_uncertain_instead_of_rejected(self):
        async def write():
            raise asyncio.TimeoutError

        with self.assertRaises(write_queue.ChargerRequestOutcomeUncertain):
            await self.gate.run(
                "write",
                write,
                timeout_makes_outcome_uncertain=True,
            )

    async def test_read_timeout_remains_a_normal_poll_failure(self):
        """Read timeouts need retry, but do not imply an unknown write state."""
        async def read():
            raise asyncio.TimeoutError

        with self.assertRaises(asyncio.TimeoutError):
            await self.gate.run("read", read)


if __name__ == "__main__":
    unittest.main()
