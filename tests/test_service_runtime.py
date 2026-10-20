"""Regression tests for integration-service concurrency and failure rules."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
    / "service_runtime.py"
)
SPEC = importlib.util.spec_from_file_location(
    "growatt_thor_service_runtime_test_target",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
service_runtime = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = service_runtime
SPEC.loader.exec_module(service_runtime)


class _Coordinator:
    def __init__(self, *, connected=True):
        self.connected = connected


class _ChargePoint:
    """Expose controllable completion and write-priority behaviour."""

    def __init__(self):
        self.status_started = asyncio.Event()
        self.release_status = asyncio.Event()
        self.write_pending = False
        self.calls = []

    async def trigger_status(self, *, skip_if_writes_pending):
        self.calls.append(("status", skip_if_writes_pending))
        self.status_started.set()
        await self.release_status.wait()
        return not (skip_if_writes_pending and self.write_pending)

    async def trigger_external_meterval(self, *, skip_if_writes_pending):
        self.calls.append(("external_meter", skip_if_writes_pending))
        return not (skip_if_writes_pending and self.write_pending)

    async def trigger_get_configuration(self, *, skip_if_writes_pending):
        self.calls.append(("configuration", skip_if_writes_pending))
        return not (skip_if_writes_pending and self.write_pending)


class IntegrationServiceOperationsTest(unittest.IsolatedAsyncioTestCase):
    """Ensure automations cannot build duplicate service-operation backlogs."""

    def setUp(self):
        self.operations = service_runtime.IntegrationServiceOperations(
            asyncio.create_task
        )

    async def test_many_refresh_callers_share_one_physical_sequence(self):
        charge_point = _ChargePoint()
        runtime = {
            "charge_point": charge_point,
            "coordinator": _Coordinator(),
        }

        first = asyncio.create_task(self.operations.async_refresh(runtime))
        await charge_point.status_started.wait()
        followers = [
            asyncio.create_task(self.operations.async_refresh(runtime))
            for _ in range(19)
        ]
        await asyncio.sleep(0)
        charge_point.release_status.set()

        await asyncio.gather(first, *followers)

        self.assertEqual(
            charge_point.calls,
            [
                ("status", True),
                ("external_meter", True),
                ("configuration", True),
            ],
        )

    async def test_one_cancelled_caller_does_not_cancel_shared_refresh(self):
        charge_point = _ChargePoint()
        runtime = {
            "charge_point": charge_point,
            "coordinator": _Coordinator(),
        }
        cancelled_caller = asyncio.create_task(
            self.operations.async_refresh(runtime)
        )
        await charge_point.status_started.wait()
        surviving_caller = asyncio.create_task(
            self.operations.async_refresh(runtime)
        )

        cancelled_caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await cancelled_caller
        charge_point.release_status.set()

        await surviving_caller
        self.assertEqual(len(charge_point.calls), 3)

    async def test_write_queued_during_refresh_preempts_remaining_reads(self):
        charge_point = _ChargePoint()
        runtime = {
            "charge_point": charge_point,
            "coordinator": _Coordinator(),
        }
        refresh = asyncio.create_task(self.operations.async_refresh(runtime))
        await charge_point.status_started.wait()

        charge_point.write_pending = True
        charge_point.release_status.set()

        with self.assertRaises(service_runtime.ManualRefreshFailed) as raised:
            await refresh
        self.assertEqual(raised.exception.step, "status")
        self.assertEqual(charge_point.calls, [("status", True)])

    async def test_write_after_first_read_preempts_second_read(self):
        class ChargePoint(_ChargePoint):
            async def trigger_status(self, *, skip_if_writes_pending):
                self.calls.append(("status", skip_if_writes_pending))
                self.write_pending = True
                return True

        charge_point = ChargePoint()
        runtime = {
            "charge_point": charge_point,
            "coordinator": _Coordinator(),
        }

        with self.assertRaises(service_runtime.ManualRefreshFailed) as raised:
            await self.operations.async_refresh(runtime)

        self.assertEqual(raised.exception.step, "external_meter")
        self.assertEqual(
            charge_point.calls,
            [("status", True), ("external_meter", True)],
        )

    async def test_unloaded_or_disconnected_runtime_returns_an_error(self):
        for runtime in (
            {},
            {
                "charge_point": object(),
                "coordinator": _Coordinator(connected=False),
            },
        ):
            with self.subTest(runtime=runtime):
                with self.assertRaises(
                    service_runtime.ChargerServiceUnavailable
                ):
                    await self.operations.async_refresh(runtime)

    async def test_failed_refresh_releases_slot_for_explicit_retry(self):
        class ChargePoint(_ChargePoint):
            def __init__(self):
                super().__init__()
                self.attempts = 0

            async def trigger_status(self, *, skip_if_writes_pending):
                self.attempts += 1
                return self.attempts > 1

        charge_point = ChargePoint()
        charge_point.release_status.set()
        runtime = {
            "charge_point": charge_point,
            "coordinator": _Coordinator(),
        }

        with self.assertRaises(service_runtime.ManualRefreshFailed):
            await self.operations.async_refresh(runtime)
        await self.operations.async_refresh(runtime)

        self.assertEqual(charge_point.attempts, 2)

    async def test_same_target_exports_share_one_task(self):
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def export():
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return 7

        first = asyncio.create_task(
            self.operations.async_export("/tmp/export.csv", export)
        )
        await started.wait()
        followers = [
            asyncio.create_task(
                self.operations.async_export("/tmp/export.csv", export)
            )
            for _ in range(9)
        ]
        await asyncio.sleep(0)
        release.set()

        results = await asyncio.gather(first, *followers)

        self.assertEqual(calls, 1)
        self.assertEqual(results, [7] * 10)

    async def test_failed_export_releases_only_its_target_slot(self):
        attempts = 0

        async def export():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError("disk full")
            return 1

        with self.assertRaises(OSError):
            await self.operations.async_export("/tmp/export.csv", export)
        self.assertEqual(
            await self.operations.async_export("/tmp/export.csv", export),
            1,
        )
        self.assertEqual(attempts, 2)


if __name__ == "__main__":
    unittest.main()
