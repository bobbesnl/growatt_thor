"""Status availability must preserve the real backend card contract offline."""
from types import SimpleNamespace, ModuleType
import sys
import unittest
from unittest.mock import patch

from test_multi_entry import _build_coordinator
from test_energy_charged_sensor import sensor


class StatusCardContractTest(unittest.TestCase):
    def make_sensor(self):
        c = _build_coordinator()
        c.dashboard_sessions = {"items": [{"session_id": "retained", "start_time": "2026-10-01T10:00:00Z", "energy_kwh": 5}], "total_energy_kwh": 5, "total_cost": 1, "total_count": 1}
        c.connection_started_at = None
        c.last_message_at = None
        c.last_message_action = None
        c.last_heartbeat_at = None
        entity = object.__new__(sensor.StatusSensor)
        entity.coordinator = c
        entity.hass = SimpleNamespace()
        return entity

    def emitted_attributes(self, entity):
        registry = ModuleType('homeassistant.helpers.entity_registry')
        registry.async_get = lambda hass: None
        registry.async_entries_for_config_entry = lambda *args: []
        with patch.dict(sys.modules, {registry.__name__: registry}), patch.object(sys.modules['homeassistant.helpers'], 'entity_registry', registry, create=True):
            # Model HA's availability gate, rather than directly reading attributes
            # that HA would suppress for an unavailable entity.
            return entity.extra_state_attributes if entity.available else {}

    def test_disconnect_keeps_contract_and_history_in_emitted_state(self):
        entity = self.make_sensor()
        entity.coordinator.status = 'Charging'
        entity.coordinator.connected = False
        self.assertTrue(entity.available)
        self.assertEqual(entity.native_value, 'offline')
        data = self.emitted_attributes(entity)
        self.assertFalse(data['connected'])
        self.assertEqual(data['thor_card']['schema'], 1)
        self.assertEqual(data['thor_card']['sessions']['schema'], 1)
        self.assertIn('retained', [item['session_id'] for item in data['thor_card']['sessions']['items']])
        self.assertEqual(data['thor_card']['sessions']['total_energy_kwh'], 5)
        entity.coordinator.connected = True
        self.assertEqual(entity.native_value, 'charging')
        self.assertIn('thor_card', self.emitted_attributes(entity))

    def test_no_first_status_still_exposes_card_contract(self):
        entity = self.make_sensor()
        entity.coordinator.status = None
        entity.coordinator.connected = True
        self.assertIsNone(entity.native_value)
        self.assertIn('thor_card', self.emitted_attributes(entity))
        self.assertIn('offline', entity._attr_options)
