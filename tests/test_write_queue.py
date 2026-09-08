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
    coordinator._last_write_monotonic = None
    coordinator._min_write_interval = 0.0
    coordinator._poll_pause_after_write = 0.0
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


if __name__ == "__main__":
    unittest.main()
