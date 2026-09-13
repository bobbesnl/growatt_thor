"""Wire-level handler tests; install tests/requirements-auth.txt to run."""
import asyncio
import importlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

HAS_OCPP = importlib.util.find_spec('ocpp') is not None and importlib.util.find_spec('websockets') is not None
if HAS_OCPP:
    # Load the actual integration modules without executing HA's package setup.
    package = ModuleType('thor_auth_wire_target')
    package.__path__ = [str(Path(__file__).parents[1] / 'custom_components/growatt_thor')]
    sys.modules[package.__name__] = package
    server = importlib.import_module(package.__name__ + '.ocpp_server')
    auth = importlib.import_module(package.__name__ + '.authorization')


class Websocket:
    def __init__(self):
        self.sent = []

    async def send(self, value):
        self.sent.append(json.loads(value))


class Coordinator:
    def __init__(self):
        self.authorization = auth.LocalAuthorization()
        self.charger_mode = 1
        self.next_id = 40
        self.active_transaction = None
        self.stops = []

    def now(self):
        return '2026-09-04T10:00:00Z'

    def set_charge_point(self, cp_id):
        pass

    def mark_connection_activity(self, action):
        pass

    async def async_allocate_transaction_id(self):
        self.next_id += 1
        return self.next_id

    def start_transaction(self, transaction_id, id_tag, **kwargs):
        self.active_transaction = {'start': {'response': {'transaction_id': transaction_id}}}

    def stop_transaction(self, reason, **kwargs):
        self.stops.append(kwargs)


@unittest.skipUnless(HAS_OCPP, 'Install tests/requirements-auth.txt for real OCPP handler tests')
class AuthorizationWireTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.coordinator = Coordinator()
        self.ws = Websocket()
        self.hass = SimpleNamespace(data={}, loop=asyncio.get_running_loop())
        self.cp = server.GrowattChargePoint('TEST-CHARGER', self.ws, self.coordinator, self.hass)

    def restrict(self, tags='TEST-CARD', *, allow_ha_remote_start=True):
        self.coordinator.authorization.policy = auth.policy_from_input(auth.AuthorizationPolicy(), {
            auth.CONF_RESTRICT_AUTHORIZATION: True,
            auth.CONF_ALLOW_HA_REMOTE_START: allow_ha_remote_start,
            auth.CONF_AUTHORIZED_TAGS: tags,
        })

    async def request(self, action, payload):
        await self.cp.route_message(json.dumps([2, 'test-message', action, payload]))
        self.assertEqual(self.ws.sent[-1][:2], [3, 'test-message'])
        return self.ws.sent[-1][2]

    async def start(self, tag):
        return await self.request('StartTransaction', {
            'connectorId': 1, 'idTag': tag, 'meterStart': 0,
            'timestamp': '2026-09-04T10:00:00Z',
        })

    async def test_default_accepts_authorize_and_start(self):
        result = await self.request('Authorize', {'idTag': 'TEST-CARD'})
        self.assertEqual(result['idTagInfo']['status'], 'Accepted')
        self.assertEqual((await self.start('TEST-CARD'))['idTagInfo']['status'], 'Accepted')

    async def test_known_and_unknown_authorize(self):
        self.restrict()
        for tag, expected in [('TEST-CARD', 'Accepted'), ('UNKNOWN-CARD', 'Invalid')]:
            result = await self.request('Authorize', {'idTag': tag})
            self.assertEqual(result['idTagInfo']['status'], expected)

    async def test_direct_start_denied_but_transaction_retained(self):
        self.restrict()
        result = await self.start('UNKNOWN-CARD')
        self.assertEqual(result['idTagInfo']['status'], 'Invalid')
        self.assertEqual(result['transactionId'], 41)
        self.assertEqual(self.coordinator.active_transaction['start']['response']['id_tag_info']['status'], 'Invalid')
        second = await self.start('TEST-CARD')
        self.assertEqual(second['transactionId'], 42)
        self.assertEqual(second['idTagInfo']['status'], 'Accepted')

    async def test_recheck_policy_after_authorize(self):
        self.restrict()
        await self.request('Authorize', {'idTag': 'TEST-CARD'})
        self.restrict('')
        self.assertEqual((await self.start('TEST-CARD'))['idTagInfo']['status'], 'Invalid')

    async def test_stop_is_processed_without_granting_cached_access(self):
        self.restrict()
        result = await self.request('StopTransaction', {
            'transactionId': 41, 'meterStop': 12, 'idTag': 'UNKNOWN-CARD',
            'timestamp': '2026-09-04T10:01:00Z',
        })
        self.assertEqual(result, {})
        self.assertEqual(self.coordinator.stops[-1]['transaction_id'], 41)

    async def test_handler_failure_denies_without_leaking_exception_tag(self):
        with patch.object(self.coordinator.authorization, 'decide', side_effect=RuntimeError('SECRET-TEST-CARD')):
            with self.assertLogs(server._LOGGER, level='ERROR') as logs:
                result = await self.request('Authorize', {'idTag': 'SECRET-TEST-CARD'})
        self.assertEqual(result['idTagInfo']['status'], 'Invalid')
        self.assertNotIn('SECRET-TEST-CARD', '\n'.join(logs.output))

    async def test_real_library_logs_do_not_contain_tag(self):
        with self.assertLogs(server._LOGGER, level='INFO') as logs:
            await self.request('Authorize', {'idTag': 'SECRET-TEST-CARD'})
            self.cp.logger.exception('Invalid frame %s', 'SECRET-TEST-CARD')
        self.assertNotIn('SECRET-TEST-CARD', '\n'.join(logs.output))

    async def test_remote_start_denied_without_network_call_when_disabled(self):
        self.restrict(allow_ha_remote_start=False)
        self.assertEqual(await self.cp.remote_start_transaction(1, '12345678'), {'status': 'Rejected'})
        self.assertEqual(self.ws.sent, [])

    async def test_remote_start_is_allowed_without_adding_technical_tag_to_cards(self):
        self.restrict()
        with patch.object(
            self.cp,
            'call',
            return_value=SimpleNamespace(status='Accepted'),
        ):
            self.assertEqual(
                await self.cp.remote_start_transaction(1, '12345678'),
                {'status': 'Accepted'},
            )
        self.assertEqual(
            (await self.start('12345678'))['idTagInfo']['status'],
            'Accepted',
        )
        self.assertEqual(
            (await self.start('12345678'))['idTagInfo']['status'],
            'Invalid',
        )

    async def test_plug_and_charge_start_is_not_treated_as_an_rfid_card(self):
        self.restrict()
        self.coordinator.charger_mode = 3
        self.assertEqual(
            (await self.start('freevenIdTag'))['idTagInfo']['status'],
            'Accepted',
        )

    async def test_reload_restores_restricted_policy(self):
        self.restrict()
        self.coordinator.authorization = auth.LocalAuthorization(
            json.loads(json.dumps(self.coordinator.authorization.policy.as_config()))
        )
        self.assertEqual((await self.start('UNKNOWN-CARD'))['idTagInfo']['status'], 'Invalid')


if __name__ == '__main__':
    unittest.main()
