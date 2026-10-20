"""Exercise the real options flow with a minimal HA form/storage harness."""
import importlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

HAS_VOL = importlib.util.find_spec('voluptuous') is not None
HAS_SERIALIZER = importlib.util.find_spec('voluptuous_serialize') is not None
if HAS_SERIALIZER:
    # Load schema classes before load_flow temporarily patches sys.modules.
    import voluptuous_serialize


class FlowBase:
    def __init_subclass__(cls, **kwargs):
        pass

    def async_show_form(self, **kwargs):
        return kwargs

    def async_create_entry(self, **kwargs):
        return kwargs

    def async_show_menu(self, **kwargs):
        return kwargs

    def async_abort(self, **kwargs):
        return {"type": "abort", **kwargs}

    def _async_current_entries(self):
        return getattr(self, "current_entries", [])


class TextSelector:
    def __init__(self, config):
        self.config = config

    def __call__(self, value):
        if not isinstance(value, str):
            raise ValueError('Expected text')
        return value


class NumberSelector:
    """Represent HA's selector serialization boundary without starting HA."""

    def __init__(self, config):
        self.config = config

    def __call__(self, value):
        return value


def serialized_form_fields(form):
    """Use the real schema serializer; unsupported callables must fail."""
    def custom_serializer(value):
        if isinstance(value, NumberSelector):
            return {"selector": {"number": value.config}}
        return voluptuous_serialize.UNSUPPORTED

    fields = voluptuous_serialize.convert(
        form['data_schema'], custom_serializer=custom_serializer,
    )
    return {field['name']: field for field in json.loads(json.dumps(fields))}


def load_flow():
    package = ModuleType('thor_auth_flow_target')
    package.__path__ = [str(Path(__file__).parents[1] / 'custom_components/growatt_thor')]
    sys.modules[package.__name__] = package
    ha = ModuleType('homeassistant')
    ha.config_entries = SimpleNamespace(ConfigFlow=FlowBase, OptionsFlow=FlowBase)
    core = ModuleType('homeassistant.core')
    core.callback = lambda function: function
    exceptions = ModuleType('homeassistant.exceptions')
    exceptions.HomeAssistantError = Exception
    exceptions.ServiceValidationError = Exception
    selectors = ModuleType('homeassistant.helpers.selector')
    selectors.SelectSelector = selectors.TextSelector = TextSelector
    selectors.SelectSelectorConfig = selectors.TextSelectorConfig = dict
    selectors.NumberSelector = NumberSelector
    selectors.NumberSelectorConfig = dict
    selectors.NumberSelectorMode = SimpleNamespace(BOX='box')
    with patch.dict(sys.modules, {
        'homeassistant': ha, 'homeassistant.core': core,
        'homeassistant.exceptions': exceptions,
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

    async def test_entry_menu_separates_local_settings_and_actions(self):
        result = await self.flow.async_step_init()
        self.assertEqual(result['step_id'], 'init')
        self.assertEqual(
            result['menu_options'],
            ['general', 'authorization', 'confirm_ap_mode'],
        )
        general = await self.flow.async_step_general()
        field_names = {marker.schema for marker in general['data_schema'].schema}
        self.assertNotIn('charger_mode', field_names)

    @unittest.skipUnless(HAS_SERIALIZER, 'Install tests/requirements-auth.txt')
    async def test_general_form_uses_frontend_serializable_validators(self):
        self.entry.data['poll_interval'] = 45
        fields = serialized_form_fields(await self.flow.async_step_general())
        self.assertEqual(fields['poll_interval']['selector']['number'], {
            'min': self.module.MIN_POLL_INTERVAL, 'step': 1, 'mode': 'box',
        })
        self.assertEqual(fields['poll_interval']['default'], 45)
        self.assertEqual(fields['location']['type'], 'string')
        invalid = await self.flow.async_step_general({'poll_interval': 5.5})
        self.assertEqual(invalid['errors'], {'poll_interval': 'invalid_poll_interval'})
        serialized_form_fields(invalid)

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

    async def test_general_options_apply_poll_interval_to_running_schedule(self):
        updates = []
        schedule = SimpleNamespace(update=updates.append)
        self.flow.hass.data['growatt_thor']['poll_interval_schedule'] = schedule

        result = await self.flow.async_step_general({
            'poll_interval': '45',
            'location': 'Garage',
        })

        self.assertEqual(result['data'], {})
        self.assertEqual(self.entry.data['poll_interval'], 45)
        self.assertEqual(self.coordinator.location, 'Garage')
        self.assertEqual(
            self.flow.hass.data['growatt_thor']['poll_interval'],
            45,
        )
        self.assertEqual(updates, [45])

    async def test_general_options_reject_ambiguous_poll_intervals(self):
        for invalid, expected in (
            (4, 'poll_interval_too_low'),
            (5.5, 'invalid_poll_interval'),
            (float('nan'), 'invalid_poll_interval'),
        ):
            with self.subTest(invalid=invalid):
                result = await self.flow.async_step_general({
                    'poll_interval': invalid,
                    'location': 'Garage',
                })
                self.assertEqual(
                    result['errors'],
                    {'poll_interval': expected},
                )
        self.assertEqual(self.updates, [])

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


@unittest.skipUnless(HAS_VOL, 'Install tests/requirements-auth.txt for config-flow tests')
class SingleInstanceConfigFlowTest(unittest.IsolatedAsyncioTestCase):
    """The 1.7 domain-global runtime must not accept a second entry."""

    @classmethod
    def setUpClass(cls):
        cls.module, _auth = load_flow()

    async def test_second_entry_aborts_before_showing_the_form(self):
        flow = self.module.GrowattThorConfigFlow()
        flow.current_entries = [SimpleNamespace(entry_id="existing")]

        result = await flow.async_step_user()

        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "single_instance_allowed")

    async def test_first_entry_can_open_the_setup_form(self):
        flow = self.module.GrowattThorConfigFlow()
        flow.current_entries = []

        result = await flow.async_step_user()

        self.assertEqual(result["step_id"], "user")

    @unittest.skipUnless(HAS_SERIALIZER, 'Install tests/requirements-auth.txt')
    async def test_setup_form_serializes_port_and_interval_selectors(self):
        flow = self.module.GrowattThorConfigFlow()
        fields = serialized_form_fields(await flow.async_step_user())
        self.assertEqual(fields['port']['selector']['number'], {
            'min': 1, 'max': 65535, 'step': 1, 'mode': 'box',
        })
        self.assertEqual(fields['port']['default'], self.module.DEFAULT_PORT)
        self.assertEqual(fields['poll_interval']['selector']['number'], {
            'min': self.module.MIN_POLL_INTERVAL, 'step': 1, 'mode': 'box',
        })
        self.assertEqual(
            fields['poll_interval']['default'], self.module.DEFAULT_POLL_INTERVAL
        )
        # Number selectors may submit integral floats; retain strict normalization.
        result = await flow.async_step_user({
            'port': 9000.0, 'location': '', 'poll_interval': 30.0,
        })
        self.assertIs(type(result['data']['port']), int)
        self.assertIs(type(result['data']['poll_interval']), int)

    async def test_port_must_be_an_exact_protocol_port(self):
        for invalid in (0, 65536, 9000.5, float('nan')):
            with self.subTest(invalid=invalid):
                flow = self.module.GrowattThorConfigFlow()
                flow.current_entries = []
                result = await flow.async_step_user({
                    'port': invalid,
                    'location': '',
                    'poll_interval': 30,
                })
                self.assertEqual(result['errors'], {'port': 'invalid_port'})

    async def test_valid_numeric_strings_are_normalized_without_rounding(self):
        flow = self.module.GrowattThorConfigFlow()
        flow.current_entries = []

        result = await flow.async_step_user({
            'port': '9000',
            'location': '',
            'poll_interval': '30',
        })

        self.assertEqual(result['data']['port'], 9000)
        self.assertEqual(result['data']['poll_interval'], 30)


if __name__ == '__main__':
    unittest.main()
