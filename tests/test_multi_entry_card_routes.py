"""Exercise real 2.0 PV and history dispatch with two loaded entries."""
import asyncio
import importlib
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import voluptuous as vol

ROOT = Path(__file__).parents[1] / 'custom_components/growatt_thor'
NAME = 'thor_card_routes_test'
package = ModuleType(NAME)
package.__path__ = [str(ROOT)]
sys.modules[NAME] = package


def load_routes():
    exceptions = ModuleType('homeassistant.exceptions')
    exceptions.HomeAssistantError = RuntimeError
    exceptions.ServiceValidationError = RuntimeError
    ws = ModuleType('homeassistant.components.websocket_api')
    ws.websocket_command = lambda schema: lambda fn: fn
    ws.async_response = lambda fn: fn
    cv = ModuleType('homeassistant.helpers.config_validation')
    cv.string = str
    dt = ModuleType('homeassistant.util.dt')
    util = ModuleType('homeassistant.util')
    util.dt = dt
    with patch.dict(sys.modules, {
        'homeassistant.exceptions': exceptions,
        'homeassistant.components.websocket_api': ws,
        'homeassistant.helpers.config_validation': cv,
        'homeassistant.util.dt': dt,
        'homeassistant.util': util,
    }):
        pv = importlib.import_module(NAME + '.charging.pv_service')
        history = importlib.import_module(NAME + '.sessions.websocket')
    return pv, history


class CardRoutingTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pv, self.history = load_routes()
        self.handlers = {}
        self.hass = SimpleNamespace(data={'growatt_thor': {
            key: {'config_entry_id': key, 'coordinator': SimpleNamespace(charge_point_id='THOR-' + key)}
            for key in ('left', 'right')
        }}, services=SimpleNamespace(
            has_service=lambda *args: False,
            async_register=lambda domain, name, handler, **kwargs: self.handlers.update({name: handler}),
        ))

    async def test_pv_dispatch_targets_and_unloads_only_the_selected_entry(self):
        left = AsyncMock(); right = AsyncMock()
        self.hass.data['growatt_thor']['left']['pv_linkage_profile_handler'] = left
        self.hass.data['growatt_thor']['right']['pv_linkage_profile_handler'] = right
        self.pv.async_register_pv_linkage_service(self.hass)
        dispatch = self.handlers[self.pv.SERVICE]
        await dispatch(SimpleNamespace(data={'entry_id': 'right'}))
        right.assert_awaited_once(); left.assert_not_awaited()
        self.pv.async_unload_pv_linkage_service(self.hass, SimpleNamespace(entry_id='right'))
        await dispatch(SimpleNamespace(data={'entry_id': 'left'}))
        left.assert_awaited_once()
        with self.assertRaises(RuntimeError):
            await dispatch(SimpleNamespace(data={'entry_id': 'right'}))

    async def test_websocket_cannot_read_another_entries_session(self):
        csv = importlib.import_module(NAME + '.sessions.csv')
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'growatt_thor_sessions.csv'
            csv.append_session_row(path, {'session_id': 'secret-right', 'session_source': 'home_assistant', 'source_instance_id': 'right', 'energy_kwh': 7})
            self.hass.config = SimpleNamespace(path=lambda _: str(path))
            async def executor(fn, *args): return fn(*args)
            self.hass.async_add_executor_job = executor
            results=[]; errors=[]
            connection=SimpleNamespace(send_result=lambda *args: results.append(args), send_error=lambda *args: errors.append(args))
            msg={'id': 1, 'entry_id': 'left', 'session_id': 'secret-right'}
            await self.history.websocket_session_detail(self.hass, connection, msg)
            self.assertEqual(results, [])
            self.assertEqual(errors[0][1], 'not_found')
            await self.history.websocket_session_detail(self.hass, connection, {**msg, 'entry_id': 'right'})
            self.assertEqual(results[0][1]['item']['energy_kwh'], 7)
