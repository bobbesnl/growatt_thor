"""Behavioural tests for multi-step PV Linkage Apply operations."""
from __future__ import annotations

from datetime import time
from enum import Enum
import importlib.util
from pathlib import Path
import sys
import types
import unittest


class ConfigurationStatus(str, Enum):
    accepted = "Accepted"
    rejected = "Rejected"
    reboot_required = "RebootRequired"


class DataTransferStatus(str, Enum):
    accepted = "Accepted"
    rejected = "Rejected"


# The unit-test environment intentionally avoids Home Assistant's complete
# dependency tree.  Supply only the OCPP enums used by the executor while still
# loading the production implementation below.
ocpp = types.ModuleType("ocpp")
ocpp_v16 = types.ModuleType("ocpp.v16")
ocpp_enums = types.ModuleType("ocpp.v16.enums")
ocpp_enums.ConfigurationStatus = ConfigurationStatus
ocpp_enums.DataTransferStatus = DataTransferStatus
sys.modules.setdefault("ocpp", ocpp)
sys.modules.setdefault("ocpp.v16", ocpp_v16)
sys.modules.setdefault("ocpp.v16.enums", ocpp_enums)


PACKAGE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
)
PACKAGE_NAME = "growatt_thor_pv_linkage_apply_test_package"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(PACKAGE_PATH)]
sys.modules[PACKAGE_NAME] = package


def _load_module(name):
    """Load production modules without importing the HA integration package."""
    qualified_name = f"{PACKAGE_NAME}.{name}"
    spec = importlib.util.spec_from_file_location(
        qualified_name,
        PACKAGE_PATH / f"{name}.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified_name] = module
    spec.loader.exec_module(module)
    return module


configuration_writes = _load_module("configuration_writes")
pv_linkage = _load_module("pv_linkage")
write_queue = _load_module("write_queue")
pv_linkage_apply = _load_module("pv_linkage_apply")


class _FakeCoordinator:
    """Record every side effect the compound executor asks HA to expose."""

    def __init__(self):
        self._generation = 0
        self.acknowledgements = []
        self.configuration_values = {}
        self.marked_configuration_writes = []
        self.apply_result = None
        self.refresh_delays = []
        self.applied_drafts = []
        self.draft_dirty = True

    def begin_configuration_write(self, key, value):
        self._generation += 1
        return self._generation

    def acknowledge_configuration_write(
        self,
        key,
        *,
        generation,
        accepted,
        result,
    ):
        self.acknowledgements.append(
            (key, generation, accepted, result)
        )
        return True

    def update_configuration_value(self, key, value):
        self.configuration_values[key] = value

    def mark_configuration_write(
        self,
        key,
        status,
        *,
        generation,
        result,
    ):
        self.marked_configuration_writes.append(
            (key, status, generation, result)
        )

    def record_pv_linkage_apply_result(self, result):
        self.apply_result = result

    def schedule_configuration_refresh(self, *, delay=1.0):
        self.refresh_delays.append(delay)

    def mark_pv_linkage_draft_applied(self, draft):
        self.applied_drafts.append(draft)
        self.draft_dirty = False


class _FakeChargePoint:
    """Return queued results, or raise queued transport failures."""

    def __init__(self, *, configuration=(), data_transfer=()):
        self.configuration_results = list(configuration)
        self.data_transfer_results = list(data_transfer)
        self.calls = []

    async def change_configuration(self, key, value):
        self.calls.append(("configuration", key, value))
        result = self.configuration_results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    async def send_data_transfer(self, *, vendor_id, message_id, data):
        self.calls.append(("data_transfer", vendor_id, message_id, data))
        result = self.data_transfer_results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _manual_draft_and_writes():
    draft = pv_linkage.PvLinkageDraft(
        pv_linkage.PvBoostMode.MANUAL,
        manual_start=time(1, 0),
        manual_end=time(2, 0),
    )
    writes = (
        pv_linkage.ConfigurationWrite(
            "G_SolarBoost",
            "1&ManualBoost",
        ),
        pv_linkage.ConfigurationWrite(
            "G_PeriodTime",
            "1&time1=01:00-02:00",
        ),
    )
    return draft, writes


class PvLinkageApplyTest(unittest.IsolatedAsyncioTestCase):
    """Keep physical progress, user draft, and diagnostics consistent."""

    async def _apply(self, coordinator, charge_point, draft, writes):
        return await pv_linkage_apply.apply_pv_linkage_writes(
            coordinator=coordinator,
            charge_point=charge_point,
            draft=draft,
            writes=writes,
        )

    async def test_first_rejection_is_failed_without_partial_state(self):
        coordinator = _FakeCoordinator()
        charge_point = _FakeChargePoint(
            configuration=(ConfigurationStatus.rejected,)
        )
        draft, writes = _manual_draft_and_writes()

        with self.assertLogs(pv_linkage_apply._LOGGER, level="ERROR"):
            result = await self._apply(
                coordinator,
                charge_point,
                draft,
                writes,
            )

        self.assertEqual(result.status, write_queue.ChargerWriteStatus.FAILED)
        self.assertEqual(
            coordinator.apply_result.status,
            pv_linkage.PvLinkageApplyStatus.FAILED,
        )
        self.assertEqual(coordinator.apply_result.completed_steps, 0)
        self.assertEqual(coordinator.refresh_delays, [])
        self.assertTrue(coordinator.draft_dirty)
        self.assertEqual(coordinator.applied_drafts, [])

    async def test_second_configuration_rejection_is_partial_and_read_back(self):
        coordinator = _FakeCoordinator()
        charge_point = _FakeChargePoint(
            configuration=(
                ConfigurationStatus.accepted,
                ConfigurationStatus.rejected,
            )
        )
        draft, writes = _manual_draft_and_writes()

        with self.assertLogs(pv_linkage_apply._LOGGER, level="ERROR"):
            result = await self._apply(
                coordinator,
                charge_point,
                draft,
                writes,
            )

        self.assertEqual(result.status, write_queue.ChargerWriteStatus.PARTIAL)
        self.assertEqual(
            coordinator.apply_result.as_dict(),
            {
                "status": "partial",
                "completed_steps": 1,
                "total_steps": 2,
                "failed_step": "G_PeriodTime",
                "reason": "Rejected",
            },
        )
        self.assertEqual(coordinator.refresh_delays, [0])
        self.assertTrue(coordinator.draft_dirty)
        self.assertEqual(coordinator.applied_drafts, [])

    async def test_rejected_smart_target_is_also_visible_as_partial(self):
        coordinator = _FakeCoordinator()
        charge_point = _FakeChargePoint(
            configuration=(ConfigurationStatus.accepted,),
            data_transfer=(DataTransferStatus.rejected,),
        )
        draft = pv_linkage.PvLinkageDraft(
            pv_linkage.PvBoostMode.SMART,
            smart_finish=time(4, 0),
            smart_target_energy_kwh=5,
        )
        writes = (
            pv_linkage.ConfigurationWrite(
                "G_SolarBoost",
                "1&SmartBoost",
            ),
            pv_linkage.DataTransferWrite(
                "Growatt",
                "solar_target_data",
                "target",
            ),
        )

        with self.assertLogs(pv_linkage_apply._LOGGER, level="ERROR"):
            result = await self._apply(
                coordinator,
                charge_point,
                draft,
                writes,
            )

        self.assertEqual(result.status, write_queue.ChargerWriteStatus.PARTIAL)
        self.assertEqual(
            coordinator.apply_result.failed_step,
            "solar_target_data",
        )
        self.assertEqual(coordinator.refresh_delays, [0])
        self.assertTrue(coordinator.draft_dirty)

    async def test_complete_success_is_the_only_path_that_clears_draft(self):
        coordinator = _FakeCoordinator()
        charge_point = _FakeChargePoint(
            configuration=(
                ConfigurationStatus.accepted,
                ConfigurationStatus.reboot_required,
            )
        )
        draft, writes = _manual_draft_and_writes()

        result = await self._apply(
            coordinator,
            charge_point,
            draft,
            writes,
        )

        self.assertEqual(result.status, write_queue.ChargerWriteStatus.SUCCESS)
        self.assertEqual(
            coordinator.apply_result.status,
            pv_linkage.PvLinkageApplyStatus.SUCCESS,
        )
        self.assertEqual(coordinator.apply_result.completed_steps, 2)
        self.assertEqual(coordinator.applied_drafts, [draft])
        self.assertFalse(coordinator.draft_dirty)
        self.assertEqual(coordinator.refresh_delays, [1.0])

    async def test_disconnect_before_first_ack_remains_safe_to_retry(self):
        coordinator = _FakeCoordinator()
        disconnect = write_queue.ChargerConnectionUnavailable("reconnect")
        charge_point = _FakeChargePoint(configuration=(disconnect,))
        draft, writes = _manual_draft_and_writes()

        with self.assertRaises(write_queue.ChargerConnectionUnavailable):
            await self._apply(
                coordinator,
                charge_point,
                draft,
                writes,
            )

        self.assertIsNone(coordinator.apply_result)
        self.assertEqual(coordinator.refresh_delays, [])
        self.assertTrue(coordinator.draft_dirty)

    async def test_disconnect_after_first_ack_is_not_retried_as_a_whole(self):
        coordinator = _FakeCoordinator()
        disconnect = write_queue.ChargerConnectionUnavailable("reconnect")
        charge_point = _FakeChargePoint(
            configuration=(ConfigurationStatus.accepted, disconnect)
        )
        draft, writes = _manual_draft_and_writes()

        result = await self._apply(
            coordinator,
            charge_point,
            draft,
            writes,
        )

        self.assertEqual(result.status, write_queue.ChargerWriteStatus.PARTIAL)
        self.assertEqual(
            coordinator.apply_result.status,
            pv_linkage.PvLinkageApplyStatus.PARTIAL,
        )
        self.assertEqual(coordinator.refresh_delays, [0])
        self.assertEqual(
            coordinator.marked_configuration_writes[0][1],
            configuration_writes.ConfigurationWriteStatus.SKIPPED,
        )
        self.assertTrue(coordinator.draft_dirty)

    async def test_lost_second_ack_is_uncertain_and_keeps_draft(self):
        coordinator = _FakeCoordinator()
        uncertain = write_queue.ChargerRequestOutcomeUncertain("ack lost")
        charge_point = _FakeChargePoint(
            configuration=(ConfigurationStatus.accepted, uncertain)
        )
        draft, writes = _manual_draft_and_writes()

        result = await self._apply(
            coordinator,
            charge_point,
            draft,
            writes,
        )

        self.assertEqual(
            result.status,
            write_queue.ChargerWriteStatus.UNCERTAIN,
        )
        self.assertEqual(
            coordinator.apply_result.status,
            pv_linkage.PvLinkageApplyStatus.UNCERTAIN,
        )
        self.assertEqual(coordinator.apply_result.completed_steps, 1)
        self.assertEqual(coordinator.refresh_delays, [0])
        self.assertEqual(
            coordinator.marked_configuration_writes[0][1],
            configuration_writes.ConfigurationWriteStatus.UNCERTAIN,
        )
        self.assertTrue(coordinator.draft_dirty)


if __name__ == "__main__":
    unittest.main()
