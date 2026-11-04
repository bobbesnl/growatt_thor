"""GrowattOcppCharger only selects the existing Start/Stop commands."""

import types
import unittest
from unittest.mock import AsyncMock

from tests import test_charging_commands as base
from tests.support import HomeAssistantError as ActionError
from tests.support import load_package_module
from tests.support.charger_control import FakeChargerControl, StopRequest

commands = base.commands
queue = base.queue
growatt_charger = load_package_module("charging.growatt_charger", package_name=base.NAME)


class GrowattOcppChargerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        base.ChargingCommandsTest.setUp(self)
        self.stop_reasons = []
        self.results = []
        self.coordinator.record_stop_requested = lambda **kwargs: self.stop_reasons.append(kwargs)
        self.coordinator.charger_is_faulted = False
        self.coordinator.charger_reboot_pending = False
        self.coordinator.connected = True
        self.coordinator.charging_target_request = None
        self.ocpp.remote_start_transaction = AsyncMock(return_value={"status": "Accepted"})
        self.charger = growatt_charger.GrowattOcppCharger(self.coordinator)

    async def queue_write(self, callback, *args, **kwargs):
        handle = await base.ChargingCommandsTest.queue_write(self, callback, *args, **kwargs)
        terminal = handle.async_wait.return_value
        handle.add_done_callback = lambda done: done(terminal)
        return handle

    @staticmethod
    def comparable(queued):
        return [
            {key: value for key, value in kwargs.items() if key != "revalidate"}
            for kwargs in queued
        ]

    async def test_stop_queues_the_same_write_as_the_command(self):
        await commands.StopChargingCommand(self.coordinator).async_request(stop_reason="guard")
        direct = self.comparable(self.queued)
        self.queued.clear()

        await self.charger.async_stop(stop_reason="guard", on_result=self.results.append)

        self.assertEqual(self.comparable(self.queued), direct)
        self.assertEqual(self.ocpp.remote_stop_transaction.await_count, 2)
        self.ocpp.remote_stop_transaction.assert_awaited_with(transaction_id=7)
        self.assertEqual(self.stop_reasons, [{"reason": "guard"}, {"reason": "guard"}])
        self.assertEqual(
            [result.status for result in self.results], [queue.ChargerCommandStatus.CONFIRMED]
        )

    async def test_stop_rechecks_the_automatic_guard_before_sending(self):
        with self.assertRaisesRegex(ActionError, "command_not_executed"):
            await self.charger.async_stop(auto_guard=lambda: "condition_cleared")
        self.ocpp.remote_stop_transaction.assert_not_awaited()

    async def test_start_reports_the_command_block_reason(self):
        for changes in (
            {},
            {"connected": False},
            {"charger_is_faulted": True},
            {"charging_target_request": {"state": "target_accepted"}},
        ):
            with self.subTest(changes=changes):
                coordinator = types.SimpleNamespace(**{**vars(self.coordinator), **changes})
                self.assertEqual(
                    growatt_charger.GrowattOcppCharger(coordinator).start_block_reason,
                    commands.StartChargingCommand(coordinator).write_block_reason,
                )

    async def test_start_queues_the_command_with_its_wire_arguments(self):
        self.coordinator.transaction_is_active = False
        await self.charger.async_start()
        self.ocpp.remote_start_transaction.assert_awaited_once_with(
            connector_id=1, id_tag="12345678"
        )
        self.assertEqual(self.queued[0]["command_name"], "RemoteStartTransaction")
        self.assertIs(self.queued[0]["policy"], queue.VOLATILE_CONTROL_WRITE_POLICY)


class FakeChargerControlTest(unittest.IsolatedAsyncioTestCase):
    async def test_records_requests_and_reports_the_result(self):
        results = []
        fake = FakeChargerControl(stop_result="done")

        await fake.async_start()
        await fake.async_stop(stop_reason="manual", on_result=results.append)

        self.assertEqual(fake.starts, 1)
        self.assertEqual(fake.stops, [StopRequest(None, "manual", results.append)])
        self.assertEqual(results, ["done"])

    async def test_raises_the_configured_error_after_recording(self):
        fake = FakeChargerControl(error=ActionError("charger_disconnected"))
        with self.assertRaises(ActionError):
            await fake.async_stop()
        self.assertEqual(len(fake.stops), 1)


if __name__ == "__main__":
    unittest.main()
