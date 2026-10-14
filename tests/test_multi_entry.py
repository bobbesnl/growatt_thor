"""Regression tests for running several config entries side by side."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest


PACKAGE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
)
COORDINATOR_MODULE = "custom_components.growatt_thor.coordinator"


def _load_coordinator_module():
    """Import coordinator.py with minimal Home Assistant stand-ins."""
    if COORDINATOR_MODULE in sys.modules:
        return sys.modules[COORDINATOR_MODULE]

    class _DataUpdateCoordinator:
        """Minimal Home Assistant stand-in needed to import the coordinator."""

    class _Store:
        """Minimal Home Assistant storage stand-in."""

    homeassistant = types.ModuleType("homeassistant")
    helpers = types.ModuleType("homeassistant.helpers")
    update_coordinator = types.ModuleType(
        "homeassistant.helpers.update_coordinator"
    )
    storage = types.ModuleType("homeassistant.helpers.storage")
    update_coordinator.DataUpdateCoordinator = _DataUpdateCoordinator
    storage.Store = _Store
    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules.setdefault("homeassistant.helpers", helpers)
    sys.modules.setdefault(
        "homeassistant.helpers.update_coordinator",
        update_coordinator,
    )
    sys.modules.setdefault("homeassistant.helpers.storage", storage)

    package = types.ModuleType("custom_components.growatt_thor")
    package.__path__ = [str(PACKAGE_PATH)]
    sys.modules.setdefault(
        "custom_components",
        types.ModuleType("custom_components"),
    )
    sys.modules.setdefault("custom_components.growatt_thor", package)

    spec = importlib.util.spec_from_file_location(
        COORDINATOR_MODULE,
        PACKAGE_PATH / "coordinator.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


coordinator_module = _load_coordinator_module()


class _MemoryStore:
    """In-memory replacement for Home Assistant's Store."""

    def __init__(self, data=None):
        self.data = data
        self.loads = 0
        self.saved = []

    async def async_load(self):
        self.loads += 1
        return self.data

    async def async_save(self, data):
        self.saved.append(data)
        self.data = data


def _build_coordinator(store=None, legacy_store=None):
    coordinator = coordinator_module.GrowattCoordinator.__new__(
        coordinator_module.GrowattCoordinator
    )
    coordinator.updates = 0

    def _updated(_data):
        coordinator.updates += 1

    coordinator.async_set_updated_data = _updated
    coordinator.connected = True
    coordinator.charge_point_id = "XGJ0000000000001"
    coordinator.status = None
    coordinator.power = None
    coordinator.phase_power = {}
    coordinator.currents = {}
    coordinator.voltages = {}
    coordinator._store = store or _MemoryStore()
    coordinator._legacy_store = legacy_store
    coordinator._transaction_id_allocator = (
        coordinator_module.TransactionIdAllocator()
    )
    coordinator.total_energy_charged = 0.0
    coordinator._restore_last_session_state(
        coordinator_module.LastSessionState.from_dict(None)
    )
    return coordinator


def _set_charging(coordinator):
    coordinator.status = "Charging"
    coordinator.power = 547.0
    coordinator.phase_power = {"L1": 547.0, "L2": 0, "L3": 0}
    coordinator.currents = {"L1": 2.4, "L2": 0, "L3": 0}
    coordinator.voltages = {"L1": 232.0, "L2": 235.0, "L3": 235.0}


class PerEntryStateTest(unittest.TestCase):
    """Each config entry keeps its own connection and poll state."""

    def test_connection_and_poll_pause_are_per_coordinator(self):
        left = _build_coordinator()
        right = _build_coordinator()

        left.active_charge_point = object()
        left.pause_polling_until(100.0)

        self.assertIsNone(right.active_charge_point)
        self.assertEqual(right.skip_polling_until, 0.0)
        self.assertEqual(left.skip_polling_until, 100.0)

    def test_poll_pause_only_extends(self):
        coordinator = _build_coordinator()
        coordinator.pause_polling_until(100.0)
        coordinator.pause_polling_until(50.0)
        self.assertEqual(coordinator.skip_polling_until, 100.0)

    def test_storage_key_is_unique_per_entry(self):
        key_for = coordinator_module.storage_key_for_entry
        self.assertNotEqual(key_for("entry_left"), key_for("entry_right"))
        self.assertEqual(key_for(None), coordinator_module.STORAGE_KEY)


class PerEntryStorageTest(unittest.IsolatedAsyncioTestCase):
    """Per-entry storage is seeded once from the shared legacy file."""

    LEGACY = {
        "total_energy_charged": 55.531,
        "next_transaction_id": 14,
        "last_session": None,
    }

    async def test_seeds_from_legacy_and_pins_to_own_file(self):
        own = _MemoryStore()
        legacy = _MemoryStore(dict(self.LEGACY))
        coordinator = _build_coordinator(own, legacy)

        await coordinator.async_load_storage()

        self.assertAlmostEqual(coordinator.total_energy_charged, 55.531)
        self.assertEqual(
            coordinator._transaction_id_allocator.next_transaction_id,
            14,
        )
        self.assertEqual(len(own.saved), 1)
        self.assertEqual(legacy.saved, [])

    async def test_entry_without_legacy_seed_starts_fresh(self):
        own = _MemoryStore()
        coordinator = _build_coordinator(own, legacy_store=None)

        await coordinator.async_load_storage()

        self.assertEqual(coordinator.total_energy_charged, 0.0)
        self.assertEqual(own.saved, [])

    async def test_own_file_wins_over_legacy(self):
        own = _MemoryStore({"total_energy_charged": 12.0, "next_transaction_id": 3})
        legacy = _MemoryStore(dict(self.LEGACY))
        coordinator = _build_coordinator(own, legacy)

        await coordinator.async_load_storage()

        self.assertAlmostEqual(coordinator.total_energy_charged, 12.0)
        self.assertEqual(legacy.loads, 0)
        self.assertEqual(own.saved, [])


class LivePowerResetTest(unittest.TestCase):
    """Live power must not keep a stale sample after charging stops."""

    def test_suspended_ev_resets_power_and_current(self):
        coordinator = _build_coordinator()
        _set_charging(coordinator)

        coordinator.set_status("SuspendedEV")

        self.assertEqual(coordinator.status, "SuspendedEV")
        self.assertEqual(coordinator.power, 0)
        self.assertEqual(coordinator.phase_power, {"L1": 0, "L2": 0, "L3": 0})
        self.assertEqual(coordinator.currents, {"L1": 0, "L2": 0, "L3": 0})
        self.assertEqual(coordinator.voltages["L1"], 232.0)

    def test_every_non_charging_status_resets(self):
        for status in (
            "SuspendedEVSE",
            "Finishing",
            "Available",
            "Preparing",
            "Faulted",
            "Unavailable",
        ):
            with self.subTest(status=status):
                coordinator = _build_coordinator()
                _set_charging(coordinator)
                coordinator.set_status(status)
                self.assertEqual(coordinator.power, 0)

    def test_charging_status_keeps_power(self):
        coordinator = _build_coordinator()
        _set_charging(coordinator)

        coordinator.set_status("Charging")

        self.assertEqual(coordinator.power, 547.0)
        self.assertEqual(coordinator.currents["L1"], 2.4)

    def test_unknown_status_keeps_power(self):
        coordinator = _build_coordinator()
        _set_charging(coordinator)

        coordinator.set_status("SomethingNew")

        self.assertEqual(coordinator.power, 547.0)

    def test_disconnect_resets_power(self):
        coordinator = _build_coordinator()
        _set_charging(coordinator)

        coordinator.set_disconnected()

        self.assertFalse(coordinator.connected)
        self.assertEqual(coordinator.power, 0)


def _load_runtime_module():
    """Import runtime.py within the stubbed package."""
    name = "custom_components.growatt_thor.runtime"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PACKAGE_PATH / "runtime.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runtime_module = _load_runtime_module()


class _Device:
    def __init__(self, device_id, identifiers):
        self.id = device_id
        self.identifiers = identifiers


class DeviceLookupTest(unittest.TestCase):
    """The external meter device is found among the entry's own devices."""

    def test_finds_device_with_identifier(self):
        charger = _Device("charger", {("growatt_thor", "entry_left")})
        meter = _Device(
            "meter",
            {("growatt_thor", "entry_left", "grid_connection")},
        )
        found = runtime_module.find_device_with_identifier(
            [charger, meter],
            ("growatt_thor", "entry_left", "grid_connection"),
        )
        self.assertIs(found, meter)

    def test_returns_none_without_match(self):
        charger = _Device("charger", {("growatt_thor", "entry_left")})
        self.assertIsNone(
            runtime_module.find_device_with_identifier(
                [charger],
                ("growatt_thor", "entry_left", "grid_connection"),
            )
        )

    def test_deprecated_lookup_is_not_called(self):
        for path in PACKAGE_PATH.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                self.assertNotIn("registry.async_get_device(", source)
                self.assertNotIn(".async_get_device(\n", source)


class NoGlobalStateSourceTest(unittest.TestCase):
    """Guard against reintroducing a single shared state slot."""

    def test_no_shared_coordinator_or_charge_point_slot(self):
        for path in PACKAGE_PATH.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                self.assertNotIn('["coordinator"]', source)
                self.assertNotIn('.get("coordinator")', source)
                self.assertNotIn('["charge_point"]', source)
                self.assertNotIn('.get("charge_point")', source)
                self.assertNotIn('"skip_polling_until"', source)

    def test_platforms_read_their_own_entry(self):
        for name in ("sensor.py", "number.py", "switch.py", "button.py", "time.py"):
            source = (PACKAGE_PATH / name).read_text(encoding="utf-8")
            with self.subTest(file=name):
                self.assertIn("get_coordinator(hass, entry.entry_id)", source)


if __name__ == "__main__":
    unittest.main()
