"""Status availability must preserve the real backend card contract offline."""

import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from test_energy_charged_sensor import sensor
from test_multi_entry import _build_coordinator


class StatusCardContractTest(unittest.TestCase):
    def make_sensor(self):
        c = _build_coordinator()
        c.dashboard_sessions = {
            "items": [
                {
                    "session_id": "retained",
                    "start_time": "2026-10-01T10:00:00Z",
                    "energy_kwh": 5,
                }
            ],
            "total_energy_kwh": 5,
            "total_cost": 1,
            "total_count": 1,
        }
        c.connection_started_at = None
        c.last_message_at = None
        c.last_message_action = None
        c.last_heartbeat_at = None
        entity = object.__new__(sensor.StatusSensor)
        entity.coordinator = c
        entity.hass = SimpleNamespace()
        return entity

    def emitted_attributes(self, entity):
        registry = ModuleType("homeassistant.helpers.entity_registry")
        registry.async_get = lambda hass: None
        registry.async_entries_for_config_entry = lambda *args: []
        with (
            patch.dict(sys.modules, {registry.__name__: registry}),
            patch.object(
                sys.modules["homeassistant.helpers"],
                "entity_registry",
                registry,
                create=True,
            ),
        ):
            # Model HA's availability gate, rather than directly reading attributes
            # that HA would suppress for an unavailable entity.
            return entity.extra_state_attributes if entity.available else {}

    def test_disconnect_keeps_contract_and_history_in_emitted_state(self):
        entity = self.make_sensor()
        entity.coordinator.status = "Charging"
        entity.coordinator.connected = False
        self.assertTrue(entity.available)
        self.assertEqual(entity.native_value, "offline")
        data = self.emitted_attributes(entity)
        self.assertFalse(data["connected"])
        self.assertEqual(data["thor_card"]["schema"], 1)
        self.assertEqual(data["thor_card"]["sessions"]["schema"], 1)
        self.assertIn(
            "retained",
            [item["session_id"] for item in data["thor_card"]["sessions"]["items"]],
        )
        self.assertEqual(data["thor_card"]["sessions"]["total_energy_kwh"], 5)
        entity.coordinator.connected = True
        self.assertEqual(entity.native_value, "charging")
        self.assertIn("thor_card", self.emitted_attributes(entity))

    def test_no_first_status_still_exposes_card_contract(self):
        entity = self.make_sensor()
        entity.coordinator.status = None
        entity.coordinator.connected = True
        self.assertIsNone(entity.native_value)
        self.assertIn("thor_card", self.emitted_attributes(entity))
        self.assertIn("offline", entity._attr_options)

    def test_recorder_omits_card_and_activity_while_live_attributes_stay_current(self):
        entity = self.make_sensor()
        c = entity.coordinator
        c.status = "Charging"
        c.connected = True
        excluded = entity._unrecorded_attributes
        self.assertEqual(
            excluded,
            frozenset(
                {
                    "thor_card",
                    "last_message_at",
                    "last_heartbeat_at",
                    "last_message_action",
                    "connection_started_at",
                }
            ),
        )
        first = self.emitted_attributes(entity)
        c.last_message_at = "2026-10-25T10:01:00Z"
        c.last_heartbeat_at = "2026-10-25T10:01:00Z"
        c.connection_started_at = "2026-10-25T10:00:00Z"
        c.last_message_action = "Heartbeat"
        c.dashboard_sessions = {**c.dashboard_sessions, "total_energy_kwh": 8}
        latest = self.emitted_attributes(entity)
        self.assertNotEqual(first, latest)
        self.assertEqual(latest["last_message_at"], c.last_message_at)
        self.assertEqual(latest["thor_card"]["sessions"]["total_energy_kwh"], 8)

        # HA serializes only the remaining attributes, which can now deduplicate.
        def recorded(data):
            return {key: value for key, value in data.items() if key not in excluded}

        self.assertEqual(recorded(first), recorded(latest))
        self.assertEqual(recorded(latest), {"connected": True})
        self.assertEqual(entity.native_value, "charging")
        c.connected = False
        self.assertEqual(recorded(self.emitted_attributes(entity)), {"connected": False})
        self.assertEqual(entity.native_value, "offline")

    def test_all_external_meter_sensors_exclude_only_the_poll_timestamp(self):
        c = SimpleNamespace(
            external_meter_used=1,
            external_meter_wring=0,
            external_meter_last_updated_at="2026-10-25T10:00:00Z",
            external_meter_fault_connector_id=None,
            external_meter_fault_error_code=None,
            external_meter_fault_info=None,
            meterval_consecutive_timeouts=0,
            external_meter_health="healthy",
            grid_power=100,
            grid_voltages={"L1": 230, "L2": 231, "L3": 232},
            grid_currents={"L1": 1, "L2": 2, "L3": 3},
        )
        variants = [
            (sensor.GridPowerSensor, None),
            (sensor.ExternalMeterHealthSensor, None),
        ]
        variants += [
            (kind, phase)
            for kind in (sensor.GridVoltageSensor, sensor.GridCurrentSensor)
            for phase in ("L1", "L2", "L3")
        ]
        self.assertEqual(len(variants), 8)
        for kind, phase in variants:
            with self.subTest(sensor=kind.__name__, phase=phase):
                entity = object.__new__(kind)
                entity.coordinator = c
                entity.phase = phase
                self.assertEqual(entity._unrecorded_attributes, frozenset({"last_updated_at"}))
                before = entity.extra_state_attributes
                value = entity.native_value
                c.external_meter_last_updated_at = "2026-10-25T10:01:00Z"
                after = entity.extra_state_attributes
                self.assertEqual(after["last_updated_at"], c.external_meter_last_updated_at)
                self.assertEqual(entity.native_value, value)
                self.assertEqual(
                    {
                        key: item
                        for key, item in before.items()
                        if key not in entity._unrecorded_attributes
                    },
                    {
                        key: item
                        for key, item in after.items()
                        if key not in entity._unrecorded_attributes
                    },
                )
                self.assertEqual(after["vendor_used"], 1)
                c.external_meter_last_updated_at = "2026-10-25T10:00:00Z"
