"""Regression tests for charger write queue hardening."""
from __future__ import annotations

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
    coordinator._configuration_refresh_task = None
    coordinator._last_write_monotonic = None
    coordinator._min_write_interval = 0.0
    coordinator._poll_pause_after_write = 0.0
    coordinator.connected = True
    coordinator.configuration_writes = {}
    coordinator.async_set_updated_data = lambda data: None
    return coordinator


class WriteQueueTest(unittest.IsolatedAsyncioTestCase):
    """Verify deduplication and prompt transaction controls."""

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


if __name__ == "__main__":
    unittest.main()
