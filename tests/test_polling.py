"""Tests for applying poll-interval option changes to a running wait."""
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
    / "polling.py"
)
SPEC = importlib.util.spec_from_file_location(
    "growatt_thor_polling_test_target",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
polling = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = polling
SPEC.loader.exec_module(polling)


class PollIntervalScheduleTest(unittest.IsolatedAsyncioTestCase):
    """The next cycle must be measured from the latest option update."""

    async def test_update_interrupts_old_wait_and_uses_new_interval(self):
        schedule = polling.PollIntervalSchedule(60)
        waiter = asyncio.create_task(schedule.async_wait_for_next_cycle())
        await asyncio.sleep(0)

        schedule.update(0.01)

        await asyncio.wait_for(waiter, timeout=0.1)
        self.assertEqual(schedule.interval, 0.01)

    async def test_multiple_updates_use_latest_interval(self):
        schedule = polling.PollIntervalSchedule(60)
        waiter = asyncio.create_task(schedule.async_wait_for_next_cycle())
        await asyncio.sleep(0)

        schedule.update(30)
        await asyncio.sleep(0)
        schedule.update(0.01)

        await asyncio.wait_for(waiter, timeout=0.1)
        self.assertEqual(schedule.interval, 0.01)

    async def test_update_during_poll_work_is_not_lost_before_next_wait(self):
        schedule = polling.PollIntervalSchedule(60)

        schedule.update(0.01)
        await asyncio.sleep(0.02)

        await asyncio.wait_for(
            schedule.async_wait_for_next_cycle(),
            timeout=0.02,
        )


class PollIntervalWiringTest(unittest.TestCase):
    """Keep config-entry updates connected to the running poll schedule."""

    def test_setup_and_options_flow_share_the_wakeable_schedule(self):
        package_path = MODULE_PATH.parent
        setup_source = (package_path / "__init__.py").read_text(
            encoding="utf-8"
        )
        flow_source = (package_path / "config_flow.py").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "poll_interval_schedule = PollIntervalSchedule(poll_interval)",
            setup_source,
        )
        self.assertIn(
            "await poll_interval_schedule.async_wait_for_next_cycle()",
            setup_source,
        )
        self.assertIn("schedule.update(poll_interval)", flow_source)


if __name__ == "__main__":
    unittest.main()
