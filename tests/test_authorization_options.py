"""Exercise the real options flow with a minimal HA form/storage harness."""
import importlib
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

HAS_VOL = importlib.util.find_spec('voluptuous') is not None


class FlowBase:
    def __init_subclass__(cls, **kwargs):
        pass

    def async_show_form(self, **kwargs):
        return kwargs

    def async_create_entry(self, **kwargs):
        return kwargs


class TextSelector:
    def __init__(self, config):
        self.config = config

    def __call__(self, value):
        if not isinstance(value, str):
            raise ValueError('Expected text')
        return value


def load_flow():
    package = ModuleType('thor_auth_flow_target')
    package.__path__ = [str(Path(__file__).parents[1] / 'custom_components/growatt_thor')]
    sys.modules[package.__name__] = package
    ha = ModuleType('homeassistant')
    ha.config_entries = SimpleNamespace(ConfigFlow=FlowBase, OptionsFlow=FlowBase)
    core = ModuleType('homeassistant.core')
    core.callback = lambda function: function
    selectors = ModuleType('homeassistant.helpers.selector')
    selectors.SelectSelector = selectors.TextSelector = TextSelector
    selectors.SelectSelectorConfig = selectors.TextSelectorConfig = dict
    with patch.dict(sys.modules, {
        'homeassistant': ha, 'homeassistant.core': core,
        'homeassistant.helpers': ModuleType('homeassistant.helpers'),
        'homeassistant.helpers.selector': selectors,
    }):
        flow = importlib.import_module(package.__name__ + '.config_flow')
    return flow, importlib.import_module(package.__name__ + '.authorization')


@unittest.skipUnless(HAS_VOL, 'Install tests/requirements-auth.txt for options-flow tests')
class AuthorizationOptionsTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.module, cls.auth = load_flow()

    async def asyncSetUp(self):
        self.flow = self.module.GrowattThorOptionsFlow()
        self.entry = SimpleNamespace(data={'port': 9000, 'location': 'Test location'})
        self.flow.config_entry = self.entry
        self.coordinator = SimpleNamespace(
            authorization=self.auth.LocalAuthorization(),
        )
        self.updates = []

        def update(entry, *, data):
            self.updates.append(data)
            entry.data = data

        self.flow.hass = SimpleNamespace(
            data={'growatt_thor': {'coordinator': self.coordinator}},
            config_entries=SimpleNamespace(async_update_entry=update),
        )

    async def test_entry_route_does_not_change_charger_mode(self):
        result = await self.flow.async_step_init({'configure_authorization': True})
        self.assertEqual(result['step_id'], 'authorization')
        self.assertEqual(self.updates, [])

    async def test_save_preserves_existing_data_and_applies_live(self):
        result = await self.flow.async_step_authorization({
            'restrict_authorization': True,
            'allow_ha_remote_start': False,
            'authorized_id_tags': 'TEST-CARD',
        })
        self.assertEqual(result['data'], {})
        self.assertEqual(self.entry.data['port'], 9000)
        self.assertEqual(self.entry.data['location'], 'Test location')
        self.assertEqual(
            self.entry.data['local_authorization']['id_tags'],
            ['TEST-CARD'],
        )
        self.assertEqual(self.coordinator.authorization.policy.status('TEST-CARD'), 'Accepted')
        self.assertEqual(self.coordinator.authorization.policy.status('OTHER-CARD'), 'Invalid')
        self.assertFalse(self.coordinator.authorization.policy.allows_ha_remote_start())
        form = await self.flow.async_step_authorization()
        self.assertEqual(form['description_placeholders']['count'], '1')
        self.assertEqual(form['data_schema']({})['authorized_id_tags'], 'TEST-CARD')

    async def test_invalid_input_does_not_mutate_and_remains_editable(self):
        result = await self.flow.async_step_authorization({
            'restrict_authorization': True, 'authorized_id_tags': 'SECRET INVALID TAG',
        })
        self.assertEqual(result['errors'], {'base': 'invalid_authorization'})
        self.assertEqual(self.updates, [])
        self.assertEqual(
            result['data_schema']({})['authorized_id_tags'],
            'SECRET INVALID TAG',
        )
        self.assertTrue(result['data_schema']({})['restrict_authorization'])

    async def test_can_save_while_charger_integration_is_offline(self):
        self.flow.hass.data = {}
        await self.flow.async_step_authorization({'restrict_authorization': True})
        policy = self.auth.AuthorizationPolicy.from_config(self.entry.data['local_authorization'])
        self.assertEqual(policy.status('TEST-CARD'), 'Invalid')

    async def test_editable_list_is_persistent_and_blank_clears_it(self):
        await self.flow.async_step_authorization({
            'restrict_authorization': True, 'authorized_id_tags': 'TEST-CARD',
        })
        await self.flow.async_step_authorization({'restrict_authorization': True})
        self.assertEqual(self.coordinator.authorization.policy.status('TEST-CARD'), 'Accepted')
        await self.flow.async_step_authorization({
            'restrict_authorization': True, 'authorized_id_tags': '',
        })
        self.assertEqual(self.coordinator.authorization.policy.status('TEST-CARD'), 'Invalid')


if __name__ == '__main__':
    unittest.main()
