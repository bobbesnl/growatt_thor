"""Per-entry coordinator state: storage, poll pause and live power (F09)."""
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


def _build_coordinator(store=None, legacy_store=None, entry_id="entry_test"):
    coordinator = coordinator_module.GrowattCoordinator.__new__(
        coordinator_module.GrowattCoordinator
    )
    coordinator.updates = 0

    def _updated(_data):
        coordinator.updates += 1

    coordinator.async_set_updated_data = _updated
    coordinator.runtime_data = {}
    coordinator.source_instance_id = entry_id
    coordinator.connected = True
    coordinator._connection_changed = asyncio.Event()
    coordinator.charge_point_id = "XGJ0000000000001"
    coordinator.status = None
    coordinator.power = None
    coordinator.phase_power = {}
    coordinator.currents = {}
    coordinator.voltages = {}
    coordinator.energy = None
    coordinator.temperature = None
    coordinator.transaction_id = None
    coordinator.last_meter_values = None
    coordinator.configuration_values = {}
    coordinator._store = store or _MemoryStore()
    coordinator._legacy_store = legacy_store
    coordinator._transaction_id_allocator = (
        coordinator_module.TransactionIdAllocator()
    )
    coordinator.total_energy_charged = 0.0
    coordinator.last_charger_fault = None
    coordinator.effective_charging = coordinator_module.EffectiveChargingTracker()
    coordinator._pending_effective_charging_minutes = {}
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
    """Each config entry keeps its own connection slot and poll pause."""

    def test_connection_and_poll_pause_are_per_coordinator(self):
        left = _build_coordinator(entry_id="entry_left")
        right = _build_coordinator(entry_id="entry_right")

        left.runtime_data["charge_point"] = object()
        left.pause_polling_until(100.0)

        self.assertNotIn("charge_point", right.runtime_data)
        self.assertNotIn("skip_polling_until", right.runtime_data)
        self.assertEqual(left.runtime_data["skip_polling_until"], 100.0)

    def test_poll_pause_only_extends(self):
        coordinator = _build_coordinator()
        coordinator.pause_polling_until(100.0)
        coordinator.pause_polling_until(50.0)
        self.assertEqual(coordinator.runtime_data["skip_polling_until"], 100.0)

    def test_storage_key_is_unique_per_entry(self):
        key_for = coordinator_module.storage_key_for_entry
        self.assertNotEqual(key_for("entry_left"), key_for("entry_right"))
        self.assertEqual(
            key_for("entry_left"),
            "growatt_thor_statistics_entry_left",
        )
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
        self.assertAlmostEqual(own.saved[0]["total_energy_charged"], 55.531)
        self.assertIn("active_effective_charging", own.saved[0])
        self.assertEqual(legacy.saved, [])

    async def test_own_file_wins_over_legacy(self):
        own = _MemoryStore({"total_energy_charged": 12.0, "next_transaction_id": 3})
        legacy = _MemoryStore(dict(self.LEGACY))
        coordinator = _build_coordinator(own, legacy)

        await coordinator.async_load_storage()

        self.assertAlmostEqual(coordinator.total_energy_charged, 12.0)
        self.assertEqual(legacy.loads, 0)
        self.assertEqual(own.saved, [])

    async def test_entry_without_legacy_seed_starts_fresh(self):
        own = _MemoryStore()
        coordinator = _build_coordinator(own, legacy_store=None)

        await coordinator.async_load_storage()

        self.assertEqual(coordinator.total_energy_charged, 0.0)
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


def _meter_values(power_w, current_a, timestamp="2026-10-14T01:25:50Z"):
    return [{
        "timestamp": timestamp,
        "sampled_value": [
            {"value": str(power_w), "measurand": "Power.Active.Import", "unit": "W", "phase": "L1"},
            {"value": str(current_a), "measurand": "Current.Import", "unit": "A", "phase": "L1"},
            {"value": "228", "measurand": "Voltage", "unit": "V", "phase": "L1"},
        ],
    }]


class DelayedMeterValuesTest(unittest.TestCase):
    """A late sample must not bring charging power back (review on #58)."""

    def test_late_sample_after_suspended_ev_keeps_power_at_zero(self):
        coordinator = _build_coordinator()
        coordinator.set_status("Charging")
        coordinator.process_meter_values(_meter_values(971, 4.2))
        self.assertEqual(coordinator.power, 971)

        coordinator.set_status("SuspendedEV")
        self.assertEqual(coordinator.power, 0)

        # The THOR delivers a sample from the charging phase after the status.
        coordinator.process_meter_values(_meter_values(971, 4.2))

        self.assertEqual(coordinator.status, "SuspendedEV")
        self.assertEqual(coordinator.power, 0)
        self.assertEqual(coordinator.currents["L1"], 0)
        # The raw sample stays available for diagnostics.
        raw = coordinator.last_meter_values["meter_values"][0]
        self.assertIn("971", str(raw))
        # Non-live measurands still update.
        self.assertEqual(coordinator.voltages["L1"], 228)

    def test_valid_samples_apply_again_when_charging_resumes(self):
        coordinator = _build_coordinator()
        coordinator.set_status("Charging")
        coordinator.process_meter_values(_meter_values(971, 4.2))
        coordinator.set_status("SuspendedEV")
        coordinator.process_meter_values(_meter_values(971, 4.2))

        # Warm-up: the vehicle draws again and the charger reports Charging.
        coordinator.set_status("Charging")
        coordinator.process_meter_values(
            _meter_values(106, 0.5, timestamp="2026-10-14T06:15:37Z")
        )

        self.assertEqual(coordinator.power, 106)
        self.assertEqual(coordinator.currents["L1"], 0.5)

    def test_samples_before_any_status_are_applied(self):
        coordinator = _build_coordinator()
        coordinator.status = None

        coordinator.process_meter_values(_meter_values(547, 2.4))

        self.assertEqual(coordinator.power, 547)

    def test_late_sample_after_finishing_is_ignored(self):
        coordinator = _build_coordinator()
        coordinator.set_status("Charging")
        coordinator.process_meter_values(_meter_values(971, 4.2))
        coordinator.set_status("Finishing")

        coordinator.process_meter_values(_meter_values(971, 4.2))

        self.assertEqual(coordinator.power, 0)


class PerEntryWiringSourceTest(unittest.TestCase):
    """Keep setup, platforms and services keyed by config entry."""

    def test_platforms_read_their_own_entry(self):
        for name in (
            "sensor.py",
            "number.py",
            "switch.py",
            "button.py",
            "time.py",
            "select.py",
        ):
            source = (PACKAGE_PATH / name).read_text(encoding="utf-8")
            with self.subTest(file=name):
                self.assertIn(
                    'hass.data[DOMAIN][entry.entry_id]["coordinator"]',
                    source,
                )

    def test_setup_seeds_storage_only_for_migrated_entries(self):
        source = (PACKAGE_PATH / "__init__.py").read_text(encoding="utf-8")
        self.assertIn(
            "seed_from_legacy=await _legacy_seed_allowed(hass, entry)",
            source,
        )
        self.assertIn("coordinator.runtime_data = runtime_data", source)

    def test_refresh_accepts_an_optional_charger(self):
        source = (PACKAGE_PATH / "__init__.py").read_text(encoding="utf-8")
        services = (PACKAGE_PATH / "services.yaml").read_text(encoding="utf-8")
        self.assertIn("vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string", source)
        self.assertIn("config_entry_id:", services)


if __name__ == "__main__":
    unittest.main()
