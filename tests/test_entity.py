"""Stable device identity and lifecycle contracts for shared platform entities."""

import importlib
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from tests.support import PACKAGE_PATH


class CoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator


class EntityContractTest(unittest.TestCase):
    def setUp(self):
        package = ModuleType("thor_entity_contract_test")
        package.__path__ = [str(PACKAGE_PATH)]
        update = ModuleType("homeassistant.helpers.update_coordinator")
        update.CoordinatorEntity = CoordinatorEntity
        with patch.dict(sys.modules, {package.__name__: package, update.__name__: update}):
            self.module = importlib.import_module(package.__name__ + ".entity")
        self.entry = SimpleNamespace(entry_id="entry-test")
        self.coordinator = SimpleNamespace(hass=object())

    def test_charger_and_meter_remain_distinct_devices(self):
        charger = self.module.ThorEntity(self.coordinator, self.entry)
        meter = self.module.ThorEntity(self.coordinator, self.entry, device="meter")
        self.assertEqual(
            charger._attr_device_info,
            {
                "identifiers": {("growatt_thor", "entry-test")},
                "name": "Growatt THOR EV Charger",
                "manufacturer": "Growatt",
                "model": "THOR",
            },
        )
        self.assertEqual(
            meter._attr_device_info,
            {
                "identifiers": {("growatt_thor", "entry-test", "grid_connection")},
                "name": "Growatt THOR External Meter",
                "manufacturer": "Growatt",
                "model": "THOR External Meter",
            },
        )
        self.assertIs(charger.coordinator, self.coordinator)
        self.assertTrue(charger._attr_has_entity_name)
        self.assertFalse(hasattr(charger, "hass"))

    def test_information_attributes_cannot_mutate_another_entity(self):
        entity = self.module.ThorEntity(self.coordinator, self.entry)
        metadata = entity.information_attributes
        metadata["information"] = "changed"
        self.assertEqual(entity.information_attributes, {"information": "details"})
