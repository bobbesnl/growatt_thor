"""Exercise Stop without an entity and with conditions changing in the queue."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).parents[1] / 'custom_components/growatt_thor'
NAME = 'thor_charging_commands_test'
package = types.ModuleType(NAME)
package.__path__ = [str(ROOT)]
sys.modules[NAME] = package


def load(name):
    spec = importlib.util.spec_from_file_location(f'{NAME}.{name}', ROOT / (name.replace(".", "/") + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ActionError(Exception):
    def __init__(self, **kwargs):
        super().__init__(kwargs.get('translation_key'))


exceptions = types.ModuleType('homeassistant.exceptions')
exceptions.HomeAssistantError = ActionError
exceptions.ServiceValidationError = ActionError
commands = load('charging.commands')
queue = sys.modules[f'{NAME}.runtime.write_queue']
with patch.dict(sys.modules, {'homeassistant.exceptions': exceptions}):
    errors = load('runtime.action_errors')
sys.modules[f'{NAME}.runtime.action_errors'] = errors


class ChargingCommandsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ocpp = types.SimpleNamespace(
            remote_stop_transaction=AsyncMock(return_value={'status': 'Accepted'}),
        )
        self.hass = types.SimpleNamespace(
            data={commands.DOMAIN: {'charge_point': self.ocpp}},
            async_create_task=lambda coroutine: coroutine.close(),
        )
        self.before_send = lambda: None
        self.cancelled = 0
        self.queued = []
        self.coordinator = types.SimpleNamespace(
            hass=self.hass, transaction_id=7, transaction_is_active=True,
            status='charging', now=lambda: datetime.now(timezone.utc).isoformat(),
            async_set_updated_data=lambda _: None,
            record_stop_requested=lambda: None,
            cancel_queued_writes=lambda **kwargs: self.cancelled,
            queue_write=self.queue_write,
        )
        self.command = commands.StopChargingCommand(self.coordinator)

    async def queue_write(self, callback, *args, **kwargs):
        self.queued.append(kwargs)
        self.before_send()
        reason = kwargs['revalidate']()
        result = queue.ChargerWriteResult.skipped(reason) if reason else await callback(*args)
        terminal = queue.ChargerCommandResult.from_write_result(
            command_id='test', command_name=kwargs['command_name'],
            queued_at='now', completed_at='now', result=result,
        )
        return types.SimpleNamespace(async_wait=AsyncMock(return_value=terminal))

    async def test_manual_stop_works_without_registered_button(self):
        await self.command.async_request()
        self.ocpp.remote_stop_transaction.assert_awaited_once_with(transaction_id=7)
        self.assertEqual(self.coordinator.dashboard_command['state'], 'accepted')
        self.assertTrue(self.coordinator.transaction_is_active)
        self.assertEqual(self.queued[0]['policy'], queue.TRANSACTION_CONTROL_WRITE_POLICY)

    async def test_automatic_condition_is_rechecked_at_execution(self):
        with self.assertRaisesRegex(ActionError, 'command_not_executed'):
            await self.command.async_request(auto_guard=lambda: 'condition_cleared')
        self.ocpp.remote_stop_transaction.assert_not_awaited()

    async def test_replaced_transaction_is_not_stopped(self):
        self.before_send = lambda: setattr(self.coordinator, 'transaction_id', 8)
        with self.assertRaisesRegex(ActionError, 'command_not_executed'):
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
        self.ocpp.remote_stop_transaction.side_effect = commands.ChargerRequestOutcomeUncertain('lost reply')
        with self.assertRaisesRegex(ActionError, 'command_outcome_uncertain'):
            await self.command.async_request()
        self.assertEqual(self.ocpp.remote_stop_transaction.await_count, 1)
        self.assertEqual(self.coordinator.dashboard_command['state'], 'uncertain')
