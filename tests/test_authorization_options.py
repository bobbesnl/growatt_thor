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


class EnergySourceTranslationTest(unittest.TestCase):
    def test_optional_energy_source_step_is_complete_in_every_language(self):
        translation_dir = (
            Path(__file__).parents[1]
            / 'custom_components'
            / 'growatt_thor'
            / 'translations'
        )
        for path in sorted(translation_dir.glob('*.json')):
            payload = json.loads(path.read_text(encoding='utf-8'))
            steps = payload['options']['step']
            with self.subTest(language=path.stem):
                self.assertTrue(
                    steps['init']['menu_options']['energy_sources']
                )
                self.assertTrue(
                    steps['init']['menu_option_descriptions']['energy_sources']
                )
                self.assertEqual(
                    set(steps['energy_sources']['data']),
                    {'battery_power_entity', 'battery_power_sign'},
                )
                self.assertNotIn(
                    'battery_power_entity',
                    steps['general']['data'],
                )


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
    with patch.dict(sys.modules, {
        'homeassistant': ha, 'homeassistant.core': core,
        'homeassistant.exceptions': exceptions,
        'homeassistant.helpers': ModuleType('homeassistant.helpers'),
        'homeassistant.helpers.selector': selectors,
    }):
        flow = importlib.import_module(package.__name__ + '.config_flow')
    return flow, importlib.import_module(package.__name__ + '.charging.authorization')


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
            async_set_updated_data=lambda _: None,
        )
        self.updates = []

        def update(entry, *, data):
            self.updates.append(data)
            entry.data = data

        self.flow.hass = SimpleNamespace(
            data={'growatt_thor': {'coordinator': self.coordinator}},
            states={},
            config_entries=SimpleNamespace(async_update_entry=update),
        )

    async def test_entry_menu_separates_local_settings_and_actions(self):
        result = await self.flow.async_step_init()
        self.assertEqual(result['step_id'], 'init')
        self.assertEqual(
            result['menu_options'],
            ['general', 'energy_sources', 'site_accounting', 'authorization', 'confirm_ap_mode'],
        )
        general = await self.flow.async_step_general()
        field_names = {marker.schema for marker in general['data_schema'].schema}
        self.assertNotIn('charger_mode', field_names)
        self.assertNotIn('battery_power_entity', field_names)
        energy_sources = await self.flow.async_step_energy_sources()
        energy_fields = {
            marker.schema for marker in energy_sources['data_schema'].schema
        }
        self.assertEqual(
            energy_fields,
            {'battery_power_entity', 'battery_power_sign'},
        )

    async def test_general_form_uses_frontend_serializable_validators(self):
        form = await self.flow.async_step_general()
        fields = {
            marker.schema: validator
            for marker, validator in form['data_schema'].schema.items()
        }

        self.assertIs(fields['poll_interval'], int)
        self.assertIs(fields['location'], str)

    def site_draft(self, **changes):
        self.entry.data['battery_power_entity'] = 'sensor.battery'
        self.flow.hass.states = {
            name: SimpleNamespace(state='100', attributes={
                'unit_of_measurement': unit, 'friendly_name': 'Same friendly name',
            })
            for name, unit in (
                ('sensor.battery', 'W'), ('sensor.solar', 'W'),
                ('sensor.house', 'kW'), ('sensor.grid', 'W'),
                ('sensor.price', '€/kWh'), ('sensor.cents', 'ct/kWh'),
                ('sensor.energy', 'kWh'),
            )
        }
        return {
            'site_accounting_profile': 'pv_battery', 'site_auto_stop_mode': 'off',
            'site_grid_source': 'ha_sensor', 'site_grid_power_entity': 'sensor.grid',
            'site_grid_power_sign': 'positive_import', 'site_solar_power_entity': 'sensor.solar',
            'site_house_power_entity': 'sensor.house', 'site_tariff_entity': 'sensor.price',
            **changes,
        }

    async def test_duplicate_sources_are_rejected_without_losing_the_draft(self):
        draft = self.site_draft(site_solar_power_entity='sensor.battery')
        form = await self.flow.async_step_site_accounting(draft)
        self.assertEqual(form['errors'], {'site_solar_power_entity': 'duplicate_power_source'})
        fields = {key.schema: key for key in form['data_schema'].schema}
        self.assertEqual(fields['site_solar_power_entity'].description['suggested_value'], 'sensor.battery')
        self.assertEqual(self.updates, [])
        draft['site_solar_power_entity'] = 'sensor.grid'
        form = await self.flow.async_step_site_accounting(draft)
        self.assertEqual(set(form['errors']), {'site_solar_power_entity', 'site_grid_power_entity'})

    async def test_searchable_source_choices_show_ids_and_filter_units_and_roles(self):
        self.entry.data.update(self.site_draft())
        form = await self.flow.async_step_site_accounting()
        fields = {key.schema: value for key, value in form['data_schema'].schema.items()}
        for field in ('site_grid_power_entity', 'site_solar_power_entity', 'site_house_power_entity', 'site_tariff_entity'):
            config = fields[field].config
            self.assertEqual(config['mode'], 'dropdown')
            self.assertTrue(config['custom_value'])
            for option in config['options']:
                self.assertIn(option['value'], option['label'])
        solar = {item['value'] for item in fields['site_solar_power_entity'].config['options']}
        self.assertEqual(solar, {'sensor.solar'})
        prices = [item['value'] for item in fields['site_tariff_entity'].config['options']]
        self.assertEqual(prices, ['sensor.price'])
        battery = await self.flow.async_step_energy_sources()
        fields = {key.schema: value for key, value in battery['data_schema'].schema.items()}
        self.assertTrue(fields['battery_power_entity'].config['custom_value'])
        self.assertEqual(fields['battery_power_entity'].config['mode'], 'dropdown')
        self.assertEqual(
            [item['value'] for item in fields['battery_power_entity'].config['options']],
            ['sensor.battery'],
        )

    async def test_missing_price_selection_remains_visible_for_repair(self):
        self.entry.data.update(self.site_draft(site_tariff_entity='sensor.removed_price'))
        form = await self.flow.async_step_site_accounting()
        fields = {key.schema: value for key, value in form['data_schema'].schema.items()}
        options = fields['site_tariff_entity'].config['options']
        self.assertIn('sensor.removed_price', [item['value'] for item in options])

    async def test_typed_sensor_ids_cannot_bypass_validation(self):
        for field, entity, error in (
            ('site_solar_power_entity', 'sensor.missing', 'invalid_power_sensor'),
            ('site_house_power_entity', 'sensor.energy', 'invalid_power_sensor'),
            ('site_tariff_entity', 'sensor.cents', 'invalid_tariff_sensor'),
            ('site_solar_power_entity', 'sensor.battery', 'duplicate_power_source'),
        ):
            with self.subTest(field=field, entity=entity):
                form = await self.flow.async_step_site_accounting(self.site_draft(**{field: entity}))
                self.assertEqual(form['errors'][field], error)
        self.assertEqual(self.updates, [])

    async def test_optional_sources_can_be_cleared_without_reinserting_defaults(self):
        self.entry.data.update(self.site_draft())
        form = await self.flow.async_step_site_accounting()
        draft = self.site_draft()
        draft.pop('site_house_power_entity')
        draft.pop('site_tariff_entity')
        draft['site_fixed_price'] = -.1
        validated = form['data_schema'](draft)
        self.assertNotIn('site_house_power_entity', validated)
        self.assertNotIn('site_tariff_entity', validated)
        result = await self.flow.async_step_site_accounting(validated)
        self.assertEqual(result['data'], {})
        self.assertNotIn('site_house_power_entity', self.entry.data)
        self.assertNotIn('site_tariff_entity', self.entry.data)
        self.assertEqual(self.entry.data['site_fixed_price'], -.1)

    async def test_invalid_fixed_price_grid_source_and_missing_battery(self):
        for price in (float('nan'), float('inf')):
            form = await self.flow.async_step_site_accounting(self.site_draft(site_fixed_price=price))
            self.assertEqual(form['errors']['site_fixed_price'], 'invalid_fixed_price')
        form = await self.flow.async_step_site_accounting(self.site_draft(site_grid_source='bogus'))
        self.assertEqual(form['errors']['site_grid_source'], 'invalid_grid_source')
        draft = self.site_draft()
        self.entry.data.pop('battery_power_entity')
        form = await self.flow.async_step_site_accounting(draft)
        self.assertEqual(form['errors']['site_accounting_profile'], 'profile_requires_battery')
        self.assertEqual(self.updates, [])

    async def test_battery_edit_cannot_introduce_conflicts_or_remove_required_source(self):
        self.entry.data.update(self.site_draft())
        for value, error in (('sensor.solar', 'duplicate_power_source'), ('', 'profile_requires_battery')):
            form = await self.flow.async_step_energy_sources({
                'battery_power_entity': value, 'battery_power_sign': 'positive_charge',
            })
            self.assertEqual(form['errors']['battery_power_entity'], error)
        self.assertEqual(self.updates, [])

    async def test_stop_settings_defaults_validation_and_storage(self):
        draft = self.site_draft()
        form = await self.flow.async_step_site_accounting()
        validated = form['data_schema'](draft)
        self.assertEqual(validated['site_stop_threshold_w'], 500)
        self.assertEqual(validated['site_stop_hold_seconds'], 180)
        for key, value in (('site_stop_threshold_w', 0), ('site_stop_hold_seconds', 10),
                           ('site_stop_threshold_w', float('nan'))):
            result = await self.flow.async_step_site_accounting({**draft, key: value})
            self.assertEqual(result['errors'][key], 'invalid_stop_settings')
        await self.flow.async_step_site_accounting({**draft, 'site_stop_threshold_w': 750, 'site_stop_hold_seconds': 240})
        self.assertEqual(self.entry.data['site_stop_threshold_w'], 750)
        self.assertEqual(self.entry.data['site_stop_hold_seconds'], 240)

    async def test_site_selectors_use_user_translations_not_server_language(self):
        """HA must localize choices per browser, even on a German server."""
        translation_dir = (
            Path(__file__).parents[1]
            / 'custom_components/growatt_thor/translations'
        )
        expected = {
            'site_accounting_profile': list(self.module.PROFILES),
            'site_auto_stop_mode': list(self.module.AUTO_STOP_MODES),
            'site_grid_source': ['none', 'thor_external', 'ha_sensor'],
            'site_grid_power_sign': list(self.module.GRID_SIGNS),
        }
        for server_language in ('de', 'en', 'fr'):
            self.flow.hass.config = SimpleNamespace(language=server_language)
            form = await self.flow.async_step_site_accounting()
            fields = {
                marker.schema: validator
                for marker, validator in form['data_schema'].schema.items()
            }
            for field, options in expected.items():
                with self.subTest(server_language=server_language, field=field):
                    self.assertEqual(fields[field].config['options'], options)
                    self.assertEqual(fields[field].config['translation_key'], field)
            for path in sorted(translation_dir.glob('*.json')):
                payload = json.loads(path.read_text(encoding='utf-8'))
                with self.subTest(language=path.stem):
                    labels = payload['options']['step']['site_accounting']['data']
                    self.assertEqual(set(labels), set(fields))
                    for error in ('duplicate_power_source', 'profile_requires_battery',
                                  'invalid_grid_source', 'invalid_fixed_price'):
                        self.assertTrue(payload['options']['error'][error])
                    for field, options in expected.items():
                        translated = payload['selector'][field]['options']
                        self.assertEqual(set(translated), set(options))
                        self.assertTrue(all(translated.values()))
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

    async def test_optional_battery_power_sensor_is_saved_and_applied_live(self):
        self.flow.hass.states = {
            'sensor.home_battery_power': SimpleNamespace(
                state='1.5',
                attributes={
                    'friendly_name': 'Home battery power',
                    'unit_of_measurement': 'kW',
                },
            )
        }
        result = await self.flow.async_step_energy_sources({
            'battery_power_entity': 'sensor.home_battery_power',
            'battery_power_sign': 'positive_charge',
        })
        self.assertEqual(result['data'], {})
        self.assertEqual(
            self.entry.data['battery_power_entity'], 'sensor.home_battery_power'
        )
        self.assertEqual(self.entry.data['battery_power_sign'], 'positive_charge')
        self.assertEqual(
            self.coordinator.battery_power_entity, 'sensor.home_battery_power'
        )

    async def test_battery_selector_filters_and_orders_candidates(self):
        self.flow.hass.states = {
            'sensor.pv_power': SimpleNamespace(
                state='4000',
                attributes={'friendly_name': 'PV power', 'unit_of_measurement': 'W'},
            ),
            'sensor.battery_power': SimpleNamespace(
                state='1000',
                attributes={
                    'friendly_name': 'Battery combined power',
                    'unit_of_measurement': 'W',
                },
            ),
            'sensor.battery_energy': SimpleNamespace(
                state='8',
                attributes={
                    'friendly_name': 'Battery energy',
                    'unit_of_measurement': 'kWh',
                },
            ),
        }
        form = await self.flow.async_step_energy_sources()
        fields = {
            marker.schema: validator
            for marker, validator in form['data_schema'].schema.items()
        }
        options = fields['battery_power_entity'].config['options']
        self.assertEqual(
            [option['value'] for option in options],
            ['sensor.battery_power', 'sensor.pv_power'],
        )

    async def test_battery_sensor_requires_a_power_unit(self):
        self.flow.hass.states = {
            'sensor.battery_energy': SimpleNamespace(
                state='8',
                attributes={'unit_of_measurement': 'kWh'},
            )
        }
        result = await self.flow.async_step_energy_sources({
            'battery_power_entity': 'sensor.battery_energy',
            'battery_power_sign': 'positive_discharge',
        })
        self.assertEqual(
            result['errors'], {'battery_power_entity': 'invalid_power_sensor'}
        )
        self.assertEqual(self.updates, [])

    async def test_general_save_preserves_optional_energy_source(self):
        self.entry.data.update({
            'battery_power_entity': 'sensor.battery_power',
            'battery_power_sign': 'positive_charge',
        })

        await self.flow.async_step_general({
            'poll_interval': 30,
            'location': 'Garage',
        })

        self.assertEqual(
            self.entry.data['battery_power_entity'],
            'sensor.battery_power',
        )
        self.assertEqual(self.entry.data['battery_power_sign'], 'positive_charge')

    async def test_blank_energy_source_disables_battery_flow_live(self):
        self.entry.data.update({
            'battery_power_entity': 'sensor.battery_power',
            'battery_power_sign': 'positive_charge',
        })
        self.coordinator.battery_power_entity = 'sensor.battery_power'
        self.coordinator.battery_power_sign = 'positive_charge'

        result = await self.flow.async_step_energy_sources({
            'battery_power_entity': '',
            'battery_power_sign': 'invalid-but-irrelevant',
        })

        self.assertEqual(result['data'], {})
        self.assertNotIn('battery_power_entity', self.entry.data)
        self.assertNotIn('battery_power_sign', self.entry.data)
        self.assertIsNone(self.coordinator.battery_power_entity)
        self.assertEqual(
            self.coordinator.battery_power_sign,
            'positive_discharge',
        )


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
        fields = {
            marker.schema: validator
            for marker, validator in result['data_schema'].schema.items()
        }
        self.assertIs(fields['port'], int)
        self.assertIs(fields['poll_interval'], int)

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
