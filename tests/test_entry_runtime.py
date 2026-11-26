"""Typed runtime retains mapping presence and entry ownership across reloads."""

import unittest

from tests.support import build_coordinator, load_package_module

entry_module = load_package_module("runtime.entry")
ownership = load_package_module("runtime.ownership")


class TypedEntryRuntimeTest(unittest.TestCase):
    def test_fields_and_mapping_share_the_same_resource(self):
        runtime = entry_module.EntryRuntime()
        coordinator = object()
        runtime.coordinator = coordinator
        runtime["charge_point"] = None
        self.assertIs(runtime.coordinator, coordinator)
        self.assertIn("charge_point", runtime)
        self.assertIsNone(runtime["charge_point"])
        self.assertEqual(list(runtime), ["coordinator", "charge_point"])
        with self.assertRaises(AttributeError):
            runtime.accidental_resource = object()
        with self.assertRaises(KeyError):
            runtime["accidental_resource"] = object()
        runtime.clear()
        self.assertEqual(dict(runtime), {})
        self.assertIsNone(runtime.coordinator)
        with self.assertRaises(KeyError):
            _ = runtime["charge_point"]

    def test_released_runtime_cannot_remove_a_reloaded_entry(self):
        registry = {}
        previous = ownership.claim_entry_runtime(registry, "entry-a")
        previous["charge_point"] = object()
        self.assertTrue(ownership.release_entry_runtime(registry, "entry-a", previous))
        current = ownership.claim_entry_runtime(registry, "entry-a")
        self.assertIsInstance(current, entry_module.EntryRuntime)
        self.assertFalse(ownership.release_entry_runtime(registry, "entry-a", previous))
        self.assertIs(registry["entry-a"], current)
        self.assertIsNone(previous.charge_point)

    def test_coordinator_connection_property_follows_socket_replacement(self):
        coordinator = build_coordinator()
        first, second = object(), object()
        coordinator.runtime_data["charge_point"] = first
        self.assertIs(coordinator.charge_point, first)
        coordinator.runtime_data["charge_point"] = second
        self.assertFalse(ownership.release_active_charge_point(coordinator.runtime_data, first))
        self.assertIs(coordinator.charge_point, second)
        ownership.release_active_charge_point(coordinator.runtime_data, second)
        self.assertIsNone(coordinator.charge_point)
