"""Local PV controls share draft state and publish edits without charger writes."""

import unittest
from datetime import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests.support import build_coordinator, install_control_stubs, load_package_module

install_control_stubs()
number = load_package_module("number")
select = load_package_module("select")
time_platform = load_package_module("time")
pv = load_package_module("charging.pv_linkage")
configuration = load_package_module("configuration.values")


class PvDraftEntitiesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.coordinator = build_coordinator()
        self.coordinator.queue_write = AsyncMock()
        self.coordinator.configuration_values = {
            "G_WorkingMode": configuration.configuration_value_from_item(
                {"key": "G_WorkingMode", "value": "PVlink", "readonly": False}
            ),
            "G_SolarMode": configuration.configuration_value_from_item(
                {"key": "G_SolarMode", "value": "1&1", "readonly": False}
            ),
        }
        self.entry = SimpleNamespace(entry_id="entry-test")

    async def test_manual_time_controls_edit_the_same_draft_once_per_change(self):
        c = self.coordinator
        c.pv_draft.boost_mode = pv.PvBoostMode.MANUAL
        for kind, field, value in (
            (time_platform.PvManualBoostStartTime, "manual_start", time(1)),
            (time_platform.PvManualBoostEndTime, "manual_end", time(3)),
        ):
            with self.subTest(field=field):
                entity = kind(c, self.entry)
                before = c.updates
                await entity.async_set_value(value)
                self.assertEqual(getattr(c.pv_draft, field), value)
                self.assertEqual(entity.native_value, value)
                self.assertTrue(c.pv_draft.dirty)
                self.assertEqual(c.updates, before + 1)
        c.queue_write.assert_not_awaited()

    async def test_smart_controls_share_mode_time_and_energy_without_writes(self):
        c = self.coordinator
        mode = select.PvBoostDraftSelect(c, self.entry)
        finish = time_platform.PvSmartBoostFinishTime(c, self.entry)
        energy = number.PvSmartBoostTargetEnergyNumber(c, self.entry)

        await mode.async_select_option("smart")
        await finish.async_set_value(time(6, 30))
        await energy.async_set_native_value(12.5)

        self.assertEqual(mode.current_option, "smart")
        self.assertEqual(c.pv_draft.boost_mode, pv.PvBoostMode.SMART)
        self.assertEqual(finish.native_value, time(6, 30))
        self.assertEqual(c.pv_draft.smart_finish, time(6, 30))
        self.assertEqual(energy.native_value, 12.5)
        self.assertEqual(c.pv_draft.smart_target_energy_kwh, 12.5)
        self.assertTrue(c.pv_draft.dirty)
        self.assertEqual(c.updates, 3)
        c.queue_write.assert_not_awaited()
