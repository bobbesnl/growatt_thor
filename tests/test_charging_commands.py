"""Exercise Stop without an entity and with conditions changing in the queue."""

import sys
import types
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from tests.support import PACKAGE_PATH, load_package_module, register_package
from tests.support import HomeAssistantError as ActionError

ROOT = PACKAGE_PATH
NAME = "thor_charging_commands_test"
package = register_package(NAME)


def load(name):
    return load_package_module(name, package_name=NAME)


exceptions = types.ModuleType("homeassistant.exceptions")
exceptions.HomeAssistantError = ActionError
exceptions.ServiceValidationError = ActionError
queue = load("runtime.write_results")
with patch.dict(sys.modules, {"homeassistant.exceptions": exceptions}):
    errors = load("runtime.action_errors")
    commands = load("charging.commands")
sys.modules[f"{NAME}.runtime.action_errors"] = errors


class ChargingCommandsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ocpp = types.SimpleNamespace(
            remote_stop_transaction=AsyncMock(return_value={"status": "Accepted"}),
        )
        self.hass = types.SimpleNamespace(
            data={commands.DOMAIN: {"charge_point": self.ocpp}},
            async_create_task=lambda coroutine: coroutine.close(),
        )
        self.before_send = lambda: None
        self.cancelled = 0
        self.queued = []
        self.coordinator = types.SimpleNamespace(
            hass=self.hass,
            runtime_data=self.hass.data[commands.DOMAIN],
            transaction_id=7,
            transaction_is_active=True,
            status="charging",
            now=lambda: datetime.now(UTC).isoformat(),
            async_set_updated_data=lambda _: None,
            record_stop_requested=lambda: None,
            cancel_queued_writes=lambda **kwargs: self.cancelled,
            queue_write=self.queue_write,
        )
        self.command = commands.StopChargingCommand(self.coordinator)

    async def queue_write(self, callback, *args, **kwargs):
        self.queued.append(kwargs)
        self.before_send()
        reason = kwargs["revalidate"]()
        result = queue.ChargerWriteResult.skipped(reason) if reason else await callback(*args)
        terminal = queue.ChargerCommandResult.from_write_result(
            command_id="test",
            command_name=kwargs["command_name"],
            queued_at="now",
            completed_at="now",
            result=result,
        )
        return types.SimpleNamespace(async_wait=AsyncMock(return_value=terminal))

    async def test_manual_stop_works_without_registered_button(self):
        await self.command.async_request()
        self.ocpp.remote_stop_transaction.assert_awaited_once_with(transaction_id=7)
        self.assertEqual(self.coordinator.dashboard_command["state"], "accepted")
        self.assertTrue(self.coordinator.transaction_is_active)
        self.assertEqual(self.queued[0]["policy"], queue.TRANSACTION_CONTROL_WRITE_POLICY)

    async def test_automatic_condition_is_rechecked_at_execution(self):
        with self.assertRaisesRegex(ActionError, "command_not_executed"):
            await self.command.async_request(auto_guard=lambda: "condition_cleared")
        self.ocpp.remote_stop_transaction.assert_not_awaited()

    async def test_replaced_transaction_is_not_stopped(self):
        self.before_send = lambda: setattr(self.coordinator, "transaction_id", 8)
        with self.assertRaisesRegex(ActionError, "command_not_executed"):
            await self.command.async_request()
        self.ocpp.remote_stop_transaction.assert_not_awaited()

    async def test_cancels_unsent_start_without_inventing_transaction(self):
        self.cancelled = 1
        self.coordinator.transaction_id = None
        self.coordinator.transaction_is_active = False
        await self.command.async_request()
        self.assertEqual(self.queued, [])
        self.ocpp.remote_stop_transaction.assert_not_awaited()

    async def test_uncertain_outcome_is_reported_without_replay(self):
        self.ocpp.remote_stop_transaction.side_effect = commands.ChargerRequestOutcomeUncertain(
            "lost reply"
        )
        with self.assertRaisesRegex(ActionError, "command_outcome_uncertain"):
            await self.command.async_request()
        self.assertEqual(self.ocpp.remote_stop_transaction.await_count, 1)
        self.assertEqual(self.coordinator.dashboard_command["state"], "uncertain")


class StartChargingCommandsTest(unittest.IsolatedAsyncioTestCase):
    """Start keeps its volatile queue policy and delayed-connection boundaries."""

    def setUp(self):
        ChargingCommandsTest.setUp(self)
        self.coordinator.transaction_is_active = False
        self.coordinator.charger_is_faulted = False
        self.coordinator.connected = True
        self.coordinator.charging_target_request = None
        self.ocpp.remote_start_transaction = AsyncMock(return_value={"status": "Accepted"})
        self.command = commands.StartChargingCommand(self.coordinator)

    queue_write = ChargingCommandsTest.queue_write

    async def test_start_preserves_wire_arguments_and_volatile_policy(self):
        await self.command.async_request()
        self.ocpp.remote_start_transaction.assert_awaited_once_with(
            connector_id=1, id_tag="12345678"
        )
        self.assertEqual(self.coordinator.dashboard_command["state"], "accepted")
        self.assertEqual(self.queued[0]["dedupe_key"], "charging_session_control")
        self.assertIs(self.queued[0]["policy"], queue.VOLATILE_CONTROL_WRITE_POLICY)
        self.assertFalse(self.queued[0]["rate_limited"])

    async def test_start_revalidates_a_session_started_while_queued(self):
        self.before_send = lambda: setattr(self.coordinator, "transaction_is_active", True)
        with self.assertRaises(ActionError):
            await self.command.async_request()
        self.ocpp.remote_start_transaction.assert_not_awaited()

    async def test_active_native_target_blocks_start_before_queueing(self):
        self.coordinator.charging_target_request = {"state": "target_accepted"}
        with self.assertRaises(ActionError):
            await self.command.async_request()
        self.assertEqual(self.queued, [])

    async def test_start_authorization_rejection_is_retained(self):
        self.ocpp.remote_start_transaction.return_value = {
            "status": "Rejected",
            "reason": "local_authorization_denied",
        }
        with self.assertRaises(ActionError):
            await self.command.async_request()
        self.assertEqual(self.coordinator.dashboard_command["reason"], "local_authorization_denied")

    async def test_uncertain_start_is_not_presented_as_acceptance(self):
        self.ocpp.remote_start_transaction.side_effect = commands.ChargerRequestOutcomeUncertain(
            "lost"
        )
        with self.assertRaises(ActionError):
            await self.command.async_request()
        self.assertEqual(self.coordinator.dashboard_command["state"], "uncertain")

    async def test_delayed_status_uses_the_replacement_connection(self):
        replacement = types.SimpleNamespace(trigger_status=AsyncMock())

        async def replace_after_delay(seconds):
            self.assertEqual(seconds, 2)
            self.coordinator.runtime_data["charge_point"] = replacement

        with patch.object(commands.asyncio, "sleep", side_effect=replace_after_delay):
            await self.command._post_status_update()
        replacement.trigger_status.assert_awaited_once()
