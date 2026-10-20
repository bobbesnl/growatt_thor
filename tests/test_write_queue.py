"""Regression tests for charger write queue hardening."""
from __future__ import annotations

import ast
import asyncio
from collections import deque
import importlib.util
from pathlib import Path
import sys
import types
import unittest


PACKAGE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
)
MODULE_PATH = PACKAGE_PATH / "coordinator.py"


class _DataUpdateCoordinator:
    """Minimal Home Assistant stand-in needed to import the coordinator."""


class _Store:
    """Minimal Home Assistant storage stand-in."""


homeassistant = types.ModuleType("homeassistant")
helpers = types.ModuleType("homeassistant.helpers")
update_coordinator = types.ModuleType(
    "homeassistant.helpers.update_coordinator"
)
storage = types.ModuleType("homeassistant.helpers.storage")
update_coordinator.DataUpdateCoordinator = _DataUpdateCoordinator
storage.Store = _Store
sys.modules.setdefault("homeassistant", homeassistant)
sys.modules.setdefault("homeassistant.helpers", helpers)
sys.modules.setdefault(
    "homeassistant.helpers.update_coordinator",
    update_coordinator,
)
sys.modules.setdefault("homeassistant.helpers.storage", storage)

package = types.ModuleType("custom_components.growatt_thor")
package.__path__ = [str(PACKAGE_PATH)]
sys.modules.setdefault("custom_components", types.ModuleType("custom_components"))
sys.modules.setdefault("custom_components.growatt_thor", package)

SPEC = importlib.util.spec_from_file_location(
    "custom_components.growatt_thor.coordinator",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
coordinator_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = coordinator_module
SPEC.loader.exec_module(coordinator_module)
write_queue_module = sys.modules["custom_components.growatt_thor.write_queue"]


class _FakeHass:
    def __init__(self, loop):
        self.loop = loop
        self.data = {"growatt_thor": {}}

    def async_create_task(self, coroutine):
        return asyncio.create_task(coroutine)


def _build_coordinator(loop):
    coordinator = coordinator_module.GrowattCoordinator.__new__(
        coordinator_module.GrowattCoordinator
    )
    coordinator.hass = _FakeHass(loop)
    coordinator._write_queue = deque()
    coordinator._write_lock = asyncio.Lock()
    coordinator._write_task = None
    coordinator._write_queue_changed = asyncio.Event()
    coordinator._write_queue_idle = asyncio.Event()
    coordinator._write_queue_idle.set()
    coordinator._connection_changed = asyncio.Event()
    coordinator._connection_changed.set()
    coordinator._active_write_item = None
    coordinator._shutting_down = False
    coordinator._configuration_refresh_task = None
    coordinator._auto_charge_schedule_task = None
    coordinator._last_write_monotonic = None
    coordinator._min_write_interval = 0.0
    coordinator._poll_pause_after_write = 0.0
    coordinator.connected = True
    coordinator.configuration_writes = {}
    coordinator.last_command_result = None
    coordinator.async_set_updated_data = lambda data: None
    return coordinator


class WriteQueueTest(unittest.IsolatedAsyncioTestCase):
    """Verify deduplication and prompt transaction controls."""

    def _policy(self, expires_after, reconnect=None):
        """Create a short-lived policy so timing tests stay fast."""
        if reconnect is None:
            reconnect = (
                coordinator_module.ChargerWriteReconnectPolicy.RETAIN_UNTIL_EXPIRY
            )
        return coordinator_module.ChargerWriteQueuePolicy(
            expires_after=expires_after,
            reconnect=reconnect,
        )

    async def test_configuration_queue_metadata_requires_generation(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())

        async def write():
            return None

        with self.assertRaisesRegex(ValueError, "key and generation"):
            await coordinator.queue_write(
                write,
                configuration_key="G_MaxCurrent",
            )

    async def test_command_handle_resolves_confirmed_result_with_stable_id(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())

        async def write():
            return coordinator_module.ChargerWriteResult.success("Accepted")

        first = await coordinator.queue_write(
            write,
            command_name="FirstCommand",
        )
        await coordinator._write_task
        result = await first.async_wait(timeout=0.1)

        second = await coordinator.queue_write(
            write,
            command_name="SecondCommand",
        )
        await coordinator._write_task

        self.assertNotEqual(first.command_id, second.command_id)
        self.assertEqual(result.command_id, first.command_id)
        self.assertEqual(
            result.status,
            write_queue_module.ChargerCommandStatus.CONFIRMED,
        )
        self.assertEqual(result.write_status.value, "success")
        self.assertEqual(result.charger_result, "Accepted")
        self.assertEqual(result.as_dict()["status"], "confirmed")
        self.assertEqual(result.as_dict()["write_status"], "success")
        self.assertIs(
            coordinator.last_command_result,
            await second.async_wait(timeout=0.1),
        )

    async def test_wait_timeout_does_not_cancel_later_completion(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        started = asyncio.Event()
        release = asyncio.Event()

        async def write():
            started.set()
            await release.wait()
            return coordinator_module.ChargerWriteResult.success("Accepted")

        handle = await coordinator.queue_write(write)
        await started.wait()
        with self.assertRaises(write_queue_module.ChargerCommandWaitTimeout):
            await handle.async_wait(timeout=0.01)
        self.assertFalse(handle.done)

        release.set()
        await coordinator._write_task
        self.assertEqual(
            (await handle.async_wait(timeout=0.1)).status,
            write_queue_module.ChargerCommandStatus.CONFIRMED,
        )

    async def test_replaced_and_cancelled_items_resolve_once(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())

        async def write(value):
            return coordinator_module.ChargerWriteResult.success(value)

        replaced = await coordinator.queue_write(
            write,
            "old",
            dedupe_key="shared",
        )
        current = await coordinator.queue_write(
            write,
            "new",
            dedupe_key="shared",
        )
        cancelled = await coordinator.queue_write(
            write,
            "cancelled",
            dedupe_key="cancel-lane",
        )
        self.assertEqual(
            coordinator.cancel_queued_writes(
                dedupe_key="cancel-lane",
                reason="cancelled_by_test",
            ),
            1,
        )

        replaced_result = await replaced.async_wait(timeout=0.1)
        cancelled_result = await cancelled.async_wait(timeout=0.1)
        self.assertEqual(
            replaced_result.status,
            write_queue_module.ChargerCommandStatus.SKIPPED,
        )
        self.assertEqual(replaced_result.reason, "replaced_by_newer_intent")
        self.assertEqual(
            cancelled_result.status,
            write_queue_module.ChargerCommandStatus.SKIPPED,
        )
        self.assertEqual(cancelled_result.reason, "cancelled_by_test")

        await coordinator._write_task
        self.assertEqual(
            (await current.async_wait(timeout=0.1)).status,
            write_queue_module.ChargerCommandStatus.CONFIRMED,
        )

    async def test_callback_exception_and_missing_result_resolve_terminally(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())

        async def fail():
            raise RuntimeError("boom")

        with self.assertLogs(coordinator_module._LOGGER, level="ERROR"):
            failed = await coordinator.queue_write(fail)
            await coordinator._write_task
        self.assertEqual(
            (await failed.async_wait(timeout=0.1)).status,
            write_queue_module.ChargerCommandStatus.FAILED,
        )

        async def legacy_callback():
            return None

        legacy = await coordinator.queue_write(legacy_callback)
        await coordinator._write_task
        legacy_result = await legacy.async_wait(timeout=0.1)
        self.assertEqual(
            legacy_result.status,
            write_queue_module.ChargerCommandStatus.UNCERTAIN,
        )
        self.assertEqual(legacy_result.reason, "missing_structured_outcome")

    async def test_partial_compound_result_is_exposed_as_uncertain(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())

        async def write():
            return coordinator_module.ChargerWriteResult.partial(
                "second_step_rejected"
            )

        with self.assertLogs(coordinator_module._LOGGER, level="ERROR"):
            handle = await coordinator.queue_write(write)
            await coordinator._write_task
        result = await handle.async_wait(timeout=0.1)

        self.assertEqual(
            result.status,
            write_queue_module.ChargerCommandStatus.UNCERTAIN,
        )
        self.assertEqual(result.write_status.value, "partial")
        self.assertEqual(result.reason, "second_step_rejected")

    async def test_shutdown_resolves_active_and_queued_waiters(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        started = asyncio.Event()

        async def active_write():
            started.set()
            await asyncio.Event().wait()

        async def queued_write():
            return coordinator_module.ChargerWriteResult.success()

        active = await coordinator.queue_write(
            active_write,
            rate_limited=False,
            command_name="ActiveCommand",
        )
        await started.wait()
        queued = await coordinator.queue_write(
            queued_write,
            command_name="QueuedCommand",
        )

        await coordinator.async_shutdown()

        active_result = await active.async_wait(timeout=0.1)
        queued_result = await queued.async_wait(timeout=0.1)
        self.assertEqual(
            active_result.status,
            write_queue_module.ChargerCommandStatus.UNCERTAIN,
        )
        self.assertEqual(
            active_result.reason,
            "integration_unloaded_during_execution",
        )
        self.assertEqual(
            queued_result.status,
            write_queue_module.ChargerCommandStatus.SKIPPED,
        )
        self.assertEqual(queued_result.reason, "integration_unloaded")
        self.assertTrue(coordinator._write_queue_idle.is_set())

    async def test_late_enqueue_after_shutdown_is_resolved_without_task(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        await coordinator.async_shutdown()
        calls = []

        async def write():
            calls.append("sent")

        handle = await coordinator.queue_write(write)
        result = await handle.async_wait(timeout=0.1)

        self.assertEqual(calls, [])
        self.assertEqual(
            result.status,
            write_queue_module.ChargerCommandStatus.SKIPPED,
        )
        self.assertEqual(result.reason, "integration_unloaded")
        self.assertIsNone(coordinator._write_task)

    async def test_duplicate_configuration_write_keeps_latest_value(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        calls = []

        async def write(value):
            calls.append(value)

        await coordinator.queue_write(
            write,
            "old",
            dedupe_key="G_LCDCloseEnable",
        )
        await coordinator.queue_write(
            write,
            "new",
            dedupe_key="G_LCDCloseEnable",
        )
        await coordinator._write_task

        self.assertEqual(calls, ["new"])

    async def test_replaced_cleanup_cannot_clear_newer_generation(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        calls = []
        visible_value = "13"

        async def write(value):
            calls.append(value)

        old_generation = coordinator.begin_configuration_write(
            "G_MaxCurrent",
            "13",
        )

        def restore_old_value(_result):
            nonlocal visible_value
            if coordinator.configuration_write_is_current(
                "G_MaxCurrent",
                old_generation,
            ):
                visible_value = "reported"

        await coordinator.queue_write(
            write,
            "13",
            dedupe_key="G_MaxCurrent",
            configuration_key="G_MaxCurrent",
            configuration_generation=old_generation,
            on_unsent=restore_old_value,
        )

        new_generation = coordinator.begin_configuration_write(
            "G_MaxCurrent",
            "17",
        )
        visible_value = "17"
        await coordinator.queue_write(
            write,
            "17",
            dedupe_key="G_MaxCurrent",
            configuration_key="G_MaxCurrent",
            configuration_generation=new_generation,
        )
        await coordinator._write_task

        tracked = coordinator.configuration_writes["G_MaxCurrent"]
        self.assertEqual(calls, ["17"])
        self.assertEqual(visible_value, "17")
        self.assertEqual(tracked.generation, new_generation)
        self.assertEqual(tracked.status, coordinator_module.ConfigurationWriteStatus.PENDING)
        self.assertEqual(
            tracked.superseded_outcomes[-1].result,
            "replaced_by_newer_intent",
        )

    async def test_expired_configuration_is_never_sent(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        coordinator.connected = False
        coordinator._connection_changed.clear()
        calls = []

        async def write(charge_point):
            calls.append(charge_point)

        generation = coordinator.begin_configuration_write(
            "G_MaxCurrent",
            "17",
        )
        with self.assertLogs(coordinator_module._LOGGER, level="WARNING"):
            handle = await coordinator.queue_write(
                write,
                object(),
                requires_connection=True,
                configuration_key="G_MaxCurrent",
                configuration_generation=generation,
                policy=self._policy(0.01),
            )
            await coordinator._write_task

        tracked = coordinator.configuration_writes["G_MaxCurrent"]
        self.assertEqual(calls, [])
        self.assertEqual(
            tracked.status,
            coordinator_module.ConfigurationWriteStatus.EXPIRED,
        )
        self.assertEqual(tracked.result, "expired_before_send")
        completion = await handle.async_wait(timeout=0.1)
        self.assertEqual(
            completion.status,
            write_queue_module.ChargerCommandStatus.EXPIRED,
        )

    async def test_expiry_does_not_discard_an_already_sent_outcome(self):
        """Once OCPP may have acted, its result remains authoritative."""
        coordinator = _build_coordinator(asyncio.get_running_loop())
        request_started = asyncio.Event()
        release_response = asyncio.Event()

        async def write(generation):
            request_started.set()
            await release_response.wait()
            coordinator.acknowledge_configuration_write(
                "G_MaxCurrent",
                generation=generation,
                accepted=True,
                result="Accepted",
            )
            return coordinator_module.ChargerWriteResult.success("Accepted")

        generation = coordinator.begin_configuration_write(
            "G_MaxCurrent",
            "17",
        )
        await coordinator.queue_write(
            write,
            generation,
            configuration_key="G_MaxCurrent",
            configuration_generation=generation,
            policy=self._policy(0.01),
        )
        await request_started.wait()
        await asyncio.sleep(0.02)
        release_response.set()
        await coordinator._write_task

        self.assertEqual(
            coordinator.configuration_writes["G_MaxCurrent"].status,
            coordinator_module.ConfigurationWriteStatus.AWAITING_READBACK,
        )

    async def test_short_reconnect_retains_eligible_configuration(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        coordinator.connected = False
        coordinator._connection_changed.clear()
        stale_charge_point = object()
        current_charge_point = object()
        calls = []

        async def write(charge_point):
            calls.append(charge_point)
            return coordinator_module.ChargerWriteResult.success("Accepted")

        await coordinator.queue_write(
            write,
            stale_charge_point,
            requires_connection=True,
            policy=self._policy(0.2),
        )
        await asyncio.sleep(0.01)

        coordinator.hass.data["growatt_thor"][
            "charge_point"
        ] = current_charge_point
        coordinator.connected = True
        coordinator._connection_changed.set()
        await coordinator._write_task

        self.assertEqual(calls, [current_charge_point])

    async def test_volatile_command_is_discarded_during_disconnect(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        coordinator.connected = False
        coordinator._connection_changed.clear()
        calls = []

        async def write(charge_point):
            calls.append(charge_point)

        with self.assertLogs(
            coordinator_module._LOGGER,
            level="WARNING",
        ) as logs:
            await coordinator.queue_write(
                write,
                object(),
                requires_connection=True,
                command_name="RemoteStartTransaction",
                policy=self._policy(
                    1.0,
                    coordinator_module.ChargerWriteReconnectPolicy.DISCARD_WHEN_DISCONNECTED,
                ),
            )
            await coordinator._write_task

        self.assertEqual(calls, [])
        self.assertTrue(
            any("discarded_on_disconnect" in line for line in logs.output)
        )

    async def test_volatile_command_expires_behind_active_write(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        blocker_started = asyncio.Event()
        release_blocker = asyncio.Event()
        calls = []

        async def blocker():
            calls.append("blocker")
            blocker_started.set()
            await release_blocker.wait()

        async def volatile_control():
            calls.append("volatile")

        await coordinator.queue_write(
            blocker,
            rate_limited=False,
            policy=self._policy(1.0),
        )
        await blocker_started.wait()
        await coordinator.queue_write(
            volatile_control,
            priority=True,
            rate_limited=False,
            command_name="RemoteStartTransaction",
            policy=self._policy(
                0.01,
                coordinator_module.ChargerWriteReconnectPolicy.DISCARD_WHEN_DISCONNECTED,
            ),
        )
        await asyncio.sleep(0.02)
        release_blocker.set()
        with self.assertLogs(coordinator_module._LOGGER, level="WARNING"):
            await coordinator._write_task

        self.assertEqual(calls, ["blocker"])

    async def test_superseded_expiry_cannot_clear_newer_pending_value(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        coordinator.connected = False
        coordinator._connection_changed.clear()
        calls = []
        visible_value = "17"

        async def write(charge_point, value):
            calls.append(value)
            return coordinator_module.ChargerWriteResult.success("Accepted")

        old_generation = coordinator.begin_configuration_write(
            "G_MaxCurrent",
            "13",
        )

        def restore_old_value(_result):
            nonlocal visible_value
            if coordinator.configuration_write_is_current(
                "G_MaxCurrent",
                old_generation,
            ):
                visible_value = "reported"

        await coordinator.queue_write(
            write,
            object(),
            "13",
            dedupe_key="old-max-current",
            requires_connection=True,
            configuration_key="G_MaxCurrent",
            configuration_generation=old_generation,
            policy=self._policy(0.02),
            on_unsent=restore_old_value,
        )
        await asyncio.sleep(0)

        new_generation = coordinator.begin_configuration_write(
            "G_MaxCurrent",
            "17",
        )
        await coordinator.queue_write(
            write,
            object(),
            "17",
            dedupe_key="new-max-current",
            requires_connection=True,
            configuration_key="G_MaxCurrent",
            configuration_generation=new_generation,
            policy=self._policy(0.2),
        )
        with self.assertLogs(coordinator_module._LOGGER, level="WARNING"):
            await asyncio.sleep(0.04)

        tracked = coordinator.configuration_writes["G_MaxCurrent"]
        self.assertEqual(tracked.generation, new_generation)
        self.assertEqual(tracked.requested_raw_value, "17")
        self.assertEqual(
            tracked.status,
            coordinator_module.ConfigurationWriteStatus.PENDING,
        )
        self.assertEqual(visible_value, "17")
        self.assertEqual(
            tracked.superseded_outcomes[-1].outcome,
            "expired",
        )

        coordinator.hass.data["growatt_thor"]["charge_point"] = object()
        coordinator.connected = True
        coordinator._connection_changed.set()
        await coordinator._write_task
        self.assertEqual(calls, ["17"])

    async def test_delayed_command_is_revalidated_before_execution(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        still_valid = True
        calls = []
        cleanup_results = []

        async def write():
            calls.append("sent")

        await coordinator.queue_write(
            write,
            revalidate=lambda: None if still_valid else "transaction_changed",
            on_unsent=cleanup_results.append,
        )
        still_valid = False
        with self.assertLogs(coordinator_module._LOGGER, level="WARNING"):
            await coordinator._write_task

        self.assertEqual(calls, [])
        self.assertEqual(len(cleanup_results), 1)
        self.assertEqual(
            cleanup_results[0].status,
            coordinator_module.ChargerWriteStatus.SKIPPED,
        )
        self.assertEqual(cleanup_results[0].reason, "transaction_changed")

    async def test_callback_skip_runs_the_same_unsent_cleanup(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        cleanup_results = []

        async def write():
            return coordinator_module.ChargerWriteResult.skipped(
                "active_transaction"
            )

        with self.assertLogs(coordinator_module._LOGGER, level="WARNING"):
            await coordinator.queue_write(
                write,
                on_unsent=cleanup_results.append,
            )
            await coordinator._write_task

        self.assertEqual(len(cleanup_results), 1)
        self.assertEqual(cleanup_results[0].reason, "active_transaction")

    async def test_invalid_revalidation_result_fails_closed(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        calls = []
        cleanup_results = []

        async def write():
            calls.append("sent")

        with self.assertLogs(coordinator_module._LOGGER, level="ERROR"):
            await coordinator.queue_write(
                write,
                revalidate=lambda: False,
                on_unsent=cleanup_results.append,
            )
            await coordinator._write_task

        self.assertEqual(calls, [])
        self.assertEqual(cleanup_results[0].reason, "revalidation_error")

    async def test_active_older_write_cannot_overwrite_newer_intent(self):
        """Deduplication cannot cancel an in-flight OCPP request.

        The first callback is deliberately held after it became active. A
        second HA action then records and queues a newer value for the same key.
        When the old acknowledgement arrives, its generation must keep it from
        changing either the tracked request or the optimistic visible value.
        """
        coordinator = _build_coordinator(asyncio.get_running_loop())
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        visible_values = []

        async def write(value, generation):
            if value == "13":
                first_started.set()
                await release_first.wait()
            outcome_is_current = coordinator.acknowledge_configuration_write(
                "G_MaxCurrent",
                generation=generation,
                accepted=True,
                result="Accepted",
            )
            if outcome_is_current:
                visible_values.append(value)
            return coordinator_module.ChargerWriteResult.success("Accepted")

        old_generation = coordinator.begin_configuration_write(
            "G_MaxCurrent",
            "13",
        )
        await coordinator.queue_write(
            write,
            "13",
            old_generation,
            dedupe_key="G_MaxCurrent",
            configuration_key="G_MaxCurrent",
            configuration_generation=old_generation,
        )
        await first_started.wait()

        new_generation = coordinator.begin_configuration_write(
            "G_MaxCurrent",
            "17",
        )
        await coordinator.queue_write(
            write,
            "17",
            new_generation,
            dedupe_key="G_MaxCurrent",
            configuration_key="G_MaxCurrent",
            configuration_generation=new_generation,
        )
        release_first.set()
        await coordinator._write_task

        tracked = coordinator.configuration_writes["G_MaxCurrent"]
        self.assertEqual(tracked.generation, new_generation)
        self.assertEqual(tracked.requested_raw_value, "17")
        self.assertEqual(
            tracked.status,
            coordinator_module.ConfigurationWriteStatus.AWAITING_READBACK,
        )
        self.assertEqual(visible_values, ["17"])

    async def test_stop_intent_cancels_only_a_matching_unsent_start(self):
        """Stop may retract a Start only before OCPP execution begins."""
        coordinator = _build_coordinator(asyncio.get_running_loop())
        blocker_started = asyncio.Event()
        release_blocker = asyncio.Event()
        calls = []
        cancelled_results = []

        async def blocker():
            calls.append("blocker")
            blocker_started.set()
            await release_blocker.wait()

        async def write(name):
            calls.append(name)

        await coordinator.queue_write(blocker, rate_limited=False)
        await blocker_started.wait()
        await coordinator.queue_write(
            write,
            "start",
            dedupe_key="charging_session_control",
            command_name="RemoteStartTransaction",
            priority=True,
            rate_limited=False,
            on_unsent=cancelled_results.append,
        )
        await coordinator.queue_write(
            write,
            "configuration",
            dedupe_key="G_MaxCurrent",
            command_name="ChangeConfiguration(G_MaxCurrent)",
        )

        with self.assertLogs(coordinator_module._LOGGER, level="INFO"):
            cancelled_count = coordinator.cancel_queued_writes(
                dedupe_key="charging_session_control",
                command_name="RemoteStartTransaction",
                reason="cancelled_by_stop_intent",
            )

        self.assertEqual(cancelled_count, 1)
        self.assertEqual(len(cancelled_results), 1)
        self.assertEqual(
            cancelled_results[0].status,
            coordinator_module.ChargerWriteStatus.SKIPPED,
        )
        self.assertEqual(
            cancelled_results[0].reason,
            "cancelled_by_stop_intent",
        )

        release_blocker.set()
        await coordinator._write_task
        self.assertEqual(calls, ["blocker", "configuration"])

    async def test_cancel_does_not_claim_an_active_start_was_retracted(self):
        """An in-flight request is outside the safe local-cancellation window."""
        coordinator = _build_coordinator(asyncio.get_running_loop())
        request_started = asyncio.Event()
        release_response = asyncio.Event()
        calls = []

        async def start():
            calls.append("start")
            request_started.set()
            await release_response.wait()

        await coordinator.queue_write(
            start,
            dedupe_key="charging_session_control",
            command_name="RemoteStartTransaction",
            rate_limited=False,
        )
        await request_started.wait()

        cancelled_count = coordinator.cancel_queued_writes(
            dedupe_key="charging_session_control",
            command_name="RemoteStartTransaction",
            reason="cancelled_by_stop_intent",
        )
        self.assertEqual(cancelled_count, 0)

        release_response.set()
        await coordinator._write_task
        self.assertEqual(calls, ["start"])

    async def test_new_start_replaces_stale_unsent_stop_on_shared_lane(self):
        """After the old transaction ends, the newer valid intent wins."""
        coordinator = _build_coordinator(asyncio.get_running_loop())
        blocker_started = asyncio.Event()
        release_blocker = asyncio.Event()
        calls = []
        replaced_results = []

        async def blocker():
            calls.append("blocker")
            blocker_started.set()
            await release_blocker.wait()

        async def write(name):
            calls.append(name)

        await coordinator.queue_write(blocker, rate_limited=False)
        await blocker_started.wait()
        await coordinator.queue_write(
            write,
            "stop",
            dedupe_key="charging_session_control",
            command_name="RemoteStopTransaction",
            priority=True,
            rate_limited=False,
            on_unsent=replaced_results.append,
        )
        await coordinator.queue_write(
            write,
            "start",
            dedupe_key="charging_session_control",
            command_name="RemoteStartTransaction",
            priority=True,
            rate_limited=False,
        )

        self.assertEqual(len(replaced_results), 1)
        self.assertEqual(
            replaced_results[0].reason,
            "replaced_by_newer_intent",
        )

        release_blocker.set()
        await coordinator._write_task
        self.assertEqual(calls, ["blocker", "start"])

    async def test_control_interrupts_configuration_rate_limit(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        coordinator._min_write_interval = 0.2
        coordinator._last_write_monotonic = coordinator.hass.loop.time()
        calls = []

        async def write(name):
            calls.append(name)

        await coordinator.queue_write(
            write,
            "configuration",
            command_name="ChangeConfiguration(G_LCDCloseEnable)",
        )
        await asyncio.sleep(0)

        await coordinator.queue_write(
            write,
            "start",
            priority=True,
            rate_limited=False,
            command_name="RemoteStartTransaction",
        )
        await asyncio.sleep(0.05)

        self.assertEqual(calls, ["start"])
        await coordinator._write_task
        self.assertEqual(calls, ["start", "configuration"])

    async def test_priority_controls_preserve_fifo_order(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        calls = []

        async def write(name):
            calls.append(name)

        await coordinator.queue_write(write, "configuration")
        await coordinator.queue_write(
            write,
            "start",
            priority=True,
            rate_limited=False,
        )
        await coordinator.queue_write(
            write,
            "stop",
            priority=True,
            rate_limited=False,
        )
        await coordinator._write_task

        self.assertEqual(calls, ["start", "stop", "configuration"])

    async def test_connection_bound_write_waits_and_uses_reconnected_charge_point(self):
        """An unsent command survives disconnect and never uses the old socket."""
        coordinator = _build_coordinator(asyncio.get_running_loop())
        coordinator.connected = False
        coordinator._connection_changed.clear()
        old_charge_point = object()
        new_charge_point = object()
        calls = []

        async def write(charge_point, value):
            calls.append((charge_point, value))
            return coordinator_module.ChargerWriteResult.success("Accepted")

        await coordinator.queue_write(
            write,
            old_charge_point,
            "17",
            dedupe_key="G_MaxCurrent",
            requires_connection=True,
        )
        await asyncio.sleep(0)
        self.assertEqual(calls, [])
        self.assertEqual(len(coordinator._write_queue), 1)

        coordinator.hass.data["growatt_thor"]["charge_point"] = new_charge_point
        coordinator.connected = True
        coordinator._connection_changed.set()
        await coordinator._write_task

        self.assertEqual(calls, [(new_charge_point, "17")])

    async def test_last_value_wins_while_waiting_for_reconnect(self):
        """Reconnect retention must not regress the existing deduplication rule."""
        coordinator = _build_coordinator(asyncio.get_running_loop())
        coordinator.connected = False
        coordinator._connection_changed.clear()
        old_charge_point = object()
        new_charge_point = object()
        calls = []

        async def write(charge_point, value):
            calls.append((charge_point, value))
            return coordinator_module.ChargerWriteResult.success("Accepted")

        await coordinator.queue_write(
            write,
            old_charge_point,
            "16",
            dedupe_key="G_MaxCurrent",
            requires_connection=True,
        )
        await asyncio.sleep(0)
        await coordinator.queue_write(
            write,
            old_charge_point,
            "13",
            dedupe_key="G_MaxCurrent",
            requires_connection=True,
        )

        coordinator.hass.data["growatt_thor"]["charge_point"] = new_charge_point
        coordinator.connected = True
        coordinator._connection_changed.set()
        await coordinator._write_task

        self.assertEqual(calls, [(new_charge_point, "13")])

    async def test_definitely_unsent_command_is_rebound_and_retried(self):
        """A stale connection error is safe to retry on the current connection."""
        coordinator = _build_coordinator(asyncio.get_running_loop())
        first_charge_point = object()
        second_charge_point = object()
        coordinator.hass.data["growatt_thor"]["charge_point"] = first_charge_point
        calls = []

        async def write(charge_point):
            calls.append(charge_point)
            if len(calls) == 1:
                coordinator.hass.data["growatt_thor"][
                    "charge_point"
                ] = second_charge_point
                raise coordinator_module.ChargerConnectionUnavailable(
                    "connection replaced before send"
                )
            return coordinator_module.ChargerWriteResult.success("Accepted")

        await coordinator.queue_write(
            write,
            first_charge_point,
            requires_connection=True,
        )
        await coordinator._write_task

        self.assertEqual(calls, [first_charge_point, second_charge_point])

    async def test_uncertain_command_is_not_blindly_retried(self):
        """A lost acknowledgement requires readback rather than duplicate send."""
        coordinator = _build_coordinator(asyncio.get_running_loop())
        calls = 0

        async def write():
            nonlocal calls
            calls += 1
            raise coordinator_module.ChargerRequestOutcomeUncertain(
                "connection lost after send"
            )

        with self.assertLogs(coordinator_module._LOGGER, level="WARNING") as logs:
            await coordinator.queue_write(write, command_name="ChangeConfiguration")
            await coordinator._write_task

        self.assertEqual(calls, 1)
        self.assertTrue(any("outcome uncertain" in line for line in logs.output))

    async def test_failed_outcome_is_never_logged_as_success(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())

        async def write():
            return coordinator_module.ChargerWriteResult.failed(
                "charger_rejected",
                "Rejected",
            )

        with self.assertLogs(coordinator_module._LOGGER, level="INFO") as logs:
            await coordinator.queue_write(write, command_name="ChangeConfiguration")
            await coordinator._write_task

        combined = "\n".join(logs.output)
        self.assertIn("Write failed", combined)
        self.assertNotIn("Write succeeded", combined)

    async def test_post_write_readbacks_are_coalesced_until_queue_is_idle(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        coordinator._write_queue_idle.clear()
        calls = 0

        class ChargePoint:
            async def trigger_get_configuration(self, *, skip_if_writes_pending):
                nonlocal calls
                self.skip_if_writes_pending = skip_if_writes_pending
                calls += 1
                return True

        charge_point = ChargePoint()
        coordinator.hass.data["growatt_thor"]["charge_point"] = charge_point

        first = coordinator.schedule_configuration_refresh(delay=0)
        second = coordinator.schedule_configuration_refresh(delay=0)
        self.assertIs(first, second)
        await asyncio.sleep(0)
        self.assertEqual(calls, 0)

        coordinator._write_queue_idle.set()
        self.assertTrue(await first)
        self.assertEqual(calls, 1)
        self.assertTrue(charge_point.skip_if_writes_pending)

    async def test_paired_auto_charge_edits_emit_one_final_schedule(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        coordinator.auto_charge_start_time_pending = coordinator_module.time(
            1,
            0,
        )
        coordinator.auto_charge_stop_time_pending = coordinator_module.time(
            5,
            0,
        )
        payloads = []

        async def capture_current_schedule():
            payloads.append(
                f"{coordinator.auto_charge_start_time_pending:%H:%M}-"
                f"{coordinator.auto_charge_stop_time_pending:%H:%M}"
            )

        coordinator.schedule_auto_charge_schedule_write(
            capture_current_schedule,
            delay=0.02,
        )
        await asyncio.sleep(0.005)
        coordinator.auto_charge_start_time_pending = coordinator_module.time(
            2,
            0,
        )
        coordinator.auto_charge_stop_time_pending = coordinator_module.time(
            6,
            0,
        )
        final_task = coordinator.schedule_auto_charge_schedule_write(
            capture_current_schedule,
            delay=0.01,
        )

        await final_task

        self.assertEqual(payloads, ["02:00-06:00"])

    async def test_shutdown_cancels_pending_auto_charge_debounce(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        calls = []

        async def write_schedule():
            calls.append("sent")

        task = coordinator.schedule_auto_charge_schedule_write(
            write_schedule,
            delay=60,
        )
        await asyncio.sleep(0)

        await coordinator.async_shutdown()

        self.assertTrue(task.done())
        self.assertEqual(calls, [])

    async def test_debounced_auto_charge_failure_is_not_unobserved(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())

        async def fail_to_queue_schedule():
            raise RuntimeError("queue unavailable")

        with self.assertLogs(coordinator_module._LOGGER, level="ERROR") as logs:
            task = coordinator.schedule_auto_charge_schedule_write(
                fail_to_queue_schedule,
                delay=0,
            )
            await task

        self.assertTrue(
            any(
                "Failed to queue debounced Auto Charge schedule" in line
                for line in logs.output
            )
        )
        self.assertIsNone(coordinator._auto_charge_schedule_task)

    async def test_only_the_applied_pv_draft_can_be_marked_clean(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        coordinator.pv_boost_mode_draft = coordinator_module.PvBoostMode.MANUAL
        coordinator.pv_manual_start_draft = coordinator_module.time(1, 0)
        coordinator.pv_manual_end_draft = coordinator_module.time(2, 0)
        coordinator.pv_smart_finish_draft = None
        coordinator.pv_smart_target_energy_draft = None
        coordinator.pv_linkage_draft_dirty = True

        older_draft = coordinator_module.PvLinkageDraft(
            coordinator_module.PvBoostMode.MANUAL,
            manual_start=coordinator_module.time(0, 0),
            manual_end=coordinator_module.time(2, 0),
        )
        self.assertFalse(
            coordinator.mark_pv_linkage_draft_applied(older_draft)
        )
        self.assertTrue(coordinator.pv_linkage_draft_dirty)

        current_draft = coordinator.pv_linkage_draft()
        self.assertTrue(
            coordinator.mark_pv_linkage_draft_applied(current_draft)
        )
        self.assertFalse(coordinator.pv_linkage_draft_dirty)

    async def test_partial_outcome_is_never_logged_as_success(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())

        async def write():
            return coordinator_module.ChargerWriteResult.partial(
                "G_PeriodTime_rejected",
                "Rejected",
            )

        with self.assertLogs(coordinator_module._LOGGER, level="INFO") as logs:
            await coordinator.queue_write(
                write,
                command_name="ApplyPvLinkage",
            )
            await coordinator._write_task

        combined = "\n".join(logs.output)
        self.assertIn("partially applied", combined)
        self.assertNotIn("Write succeeded", combined)


class WriteQueuePolicyWiringTest(unittest.TestCase):
    """Keep production call sites explicit about delayed-command semantics."""

    PRODUCTION_FILES = (
        "button.py",
        "config_flow.py",
        "configuration_control.py",
        "number.py",
        "select.py",
        "switch.py",
        "time.py",
    )

    def test_bundled_policy_windows_are_deliberate_and_bounded(self):
        self.assertEqual(
            write_queue_module.CONFIGURATION_WRITE_POLICY.expires_after,
            300.0,
        )
        self.assertEqual(
            write_queue_module.TRANSACTION_CONTROL_WRITE_POLICY.expires_after,
            60.0,
        )
        self.assertEqual(
            write_queue_module.VOLATILE_CONTROL_WRITE_POLICY.expires_after,
            15.0,
        )
        self.assertEqual(
            write_queue_module.VOLATILE_CONTROL_WRITE_POLICY.reconnect,
            write_queue_module.ChargerWriteReconnectPolicy.DISCARD_WHEN_DISCONNECTED,
        )

        for invalid_expiry in (0, float("nan")):
            with self.subTest(invalid_expiry=invalid_expiry):
                with self.assertRaisesRegex(ValueError, "greater than zero"):
                    write_queue_module.ChargerWriteQueuePolicy(
                        expires_after=invalid_expiry,
                        reconnect=(
                            write_queue_module.ChargerWriteReconnectPolicy.RETAIN_UNTIL_EXPIRY
                        ),
                    )

    def test_every_production_queue_call_declares_a_policy(self):
        missing = []
        for filename in self.PRODUCTION_FILES:
            tree = ast.parse((PACKAGE_PATH / filename).read_text())
            for call in (
                node for node in ast.walk(tree) if isinstance(node, ast.Call)
            ):
                if not (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "queue_write"
                ):
                    continue
                keyword_names = {keyword.arg for keyword in call.keywords}
                if "policy" not in keyword_names:
                    missing.append(f"{filename}:{call.lineno}")

        self.assertEqual(missing, [])

    def test_start_stop_and_ap_mode_use_their_specific_policies(self):
        expected = {
            ("button.py", "REMOTE_START_COMMAND"): (
                "VOLATILE_CONTROL_WRITE_POLICY",
                True,
            ),
            ("button.py", "REMOTE_STOP_COMMAND"): (
                "TRANSACTION_CONTROL_WRITE_POLICY",
                True,
            ),
            ("config_flow.py", "DataTransfer(appconfigmode)"): (
                "VOLATILE_CONTROL_WRITE_POLICY",
                False,
            ),
        }

        found = {}
        for filename in {item[0] for item in expected}:
            tree = ast.parse((PACKAGE_PATH / filename).read_text())
            for call in (
                node for node in ast.walk(tree) if isinstance(node, ast.Call)
            ):
                if not (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "queue_write"
                ):
                    continue
                keywords = {
                    keyword.arg: keyword.value
                    for keyword in call.keywords
                    if keyword.arg is not None
                }
                command = keywords.get("command_name")
                policy = keywords.get("policy")
                if not isinstance(policy, ast.Name):
                    continue
                if isinstance(command, ast.Constant):
                    command_identifier = command.value
                elif isinstance(command, ast.Name):
                    command_identifier = command.id
                else:
                    continue
                key = (filename, command_identifier)
                if key in expected:
                    found[key] = (
                        policy.id,
                        "revalidate" in keywords,
                    )

        self.assertEqual(found, expected)

    def test_stop_no_longer_invents_transaction_zero(self):
        tree = ast.parse((PACKAGE_PATH / "button.py").read_text())
        stop_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "StopChargingButton"
        )
        integer_constants = [
            node.value
            for node in ast.walk(stop_class)
            if isinstance(node, ast.Constant)
            and type(node.value) is int
        ]
        attributes = [
            node.attr
            for node in ast.walk(stop_class)
            if isinstance(node, ast.Attribute)
        ]

        self.assertNotIn(0, integer_constants)
        self.assertIn("transaction_id", attributes)
        self.assertIn("transaction_is_active", attributes)

    def test_start_and_stop_share_one_opposing_intent_queue_lane(self):
        tree = ast.parse((PACKAGE_PATH / "button.py").read_text())
        classes = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name in {"StartChargingButton", "StopChargingButton"}
        }

        for class_name in classes:
            queue_call = next(
                node
                for node in ast.walk(classes[class_name])
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "queue_write"
            )
            keywords = {
                keyword.arg: keyword.value
                for keyword in queue_call.keywords
                if keyword.arg is not None
            }
            dedupe_key = keywords["dedupe_key"]
            with self.subTest(class_name=class_name):
                self.assertIsInstance(dedupe_key, ast.Name)
                self.assertEqual(
                    dedupe_key.id,
                    "SESSION_CONTROL_DEDUPE_KEY",
                )

        stop_calls = {
            node.func.attr: node
            for node in ast.walk(classes["StopChargingButton"])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }
        cancellation = stop_calls["cancel_queued_writes"]
        cancellation_keywords = {
            keyword.arg: keyword.value
            for keyword in cancellation.keywords
            if keyword.arg is not None
        }
        self.assertEqual(
            cancellation_keywords["command_name"].id,
            "REMOTE_START_COMMAND",
        )
        self.assertEqual(
            cancellation_keywords["reason"].id,
            "STOP_CANCELLED_START_REASON",
        )


if __name__ == "__main__":
    unittest.main()
