"""Per-entry coordinator state: storage, poll pause and live power (F09)."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PACKAGE_PATH = Path(__file__).parents[1] / "custom_components" / "growatt_thor"
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
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")
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
    def init_base(self, hass, *args, **kwargs):
        self.hass = hass

    with (
        patch.object(coordinator_module.DataUpdateCoordinator, "__init__", init_base),
        patch.object(coordinator_module, "Store", lambda *args: _MemoryStore()),
    ):
        coordinator = coordinator_module.GrowattCoordinator(
            types.SimpleNamespace(config=None), entry_id
        )
    coordinator.updates = 0

    def _updated(_data):
        coordinator.updates += 1

    coordinator.async_set_updated_data = _updated
    coordinator.runtime_data = {}
    coordinator.source_instance_id = entry_id
    coordinator.connected = True
    coordinator._connection_changed.clear()
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
    coordinator._transaction_id_allocator = coordinator_module.TransactionIdAllocator()
    coordinator.total_energy_charged = 0.0
    coordinator.last_charger_fault = None
    coordinator.effective_charging = coordinator_module.EffectiveChargingTracker()
    coordinator._pending_effective_charging_minutes = {}
    coordinator._restore_last_session_state(coordinator_module.LastSessionState.from_dict(None))
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
    return [
        {
            "timestamp": timestamp,
            "sampled_value": [
                {
                    "value": str(power_w),
                    "measurand": "Power.Active.Import",
                    "unit": "W",
                    "phase": "L1",
                },
                {
                    "value": str(current_a),
                    "measurand": "Current.Import",
                    "unit": "A",
                    "phase": "L1",
                },
                {"value": "228", "measurand": "Voltage", "unit": "V", "phase": "L1"},
            ],
        }
    ]


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
        coordinator.process_meter_values(_meter_values(106, 0.5, timestamp="2026-10-14T06:15:37Z"))

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


class TransactionBindingTest(unittest.IsolatedAsyncioTestCase):
    def make_coordinator(self):
        c = _build_coordinator()
        c.hass.async_create_task = lambda coro: coro.close()
        c._schedule_storage_save = lambda: None
        c.start_transaction(42, id_tag="private", meter_start=0)
        return c

    async def test_foreign_and_duplicate_stops_preserve_session(self):
        c = self.make_coordinator()
        active = c.active_transaction
        c.stop_transaction(transaction_id=41, meter_stop=100)
        self.assertIs(c.active_transaction, active)
        self.assertEqual(c.transaction_id, 42)
        c.stop_transaction(transaction_id=42, meter_stop=200)
        completed = c.last_completed_transaction
        c.stop_transaction(transaction_id=42, meter_stop=200)
        c.stop_transaction(transaction_id=999, meter_stop=300)
        self.assertIs(c.last_completed_transaction, completed)
        c.start_transaction(43, meter_start=200)
        c.stop_transaction(transaction_id=42, meter_stop=200)
        self.assertEqual(c.transaction_id, 43)

    async def test_stale_meter_values_do_not_replace_or_resurrect_transaction(self):
        c = self.make_coordinator()
        c.process_meter_values([], transaction_id=41)
        self.assertEqual(c.transaction_id, 42)
        self.assertIsNone(c.last_meter_values)
        c.stop_transaction(transaction_id=42)
        c.process_meter_values([], transaction_id=42)
        self.assertIsNone(c.transaction_id)
        self.assertFalse(c.transaction_is_active)

    async def test_reconnect_recovers_id_only_after_charging_status(self):
        c = self.make_coordinator()
        c.transaction_id = None
        c.active_transaction = None
        c.status = "Available"
        c.process_meter_values([], transaction_id=42)
        self.assertIsNone(c.transaction_id)
        c.status = "Charging"
        c.process_meter_values([], transaction_id=42)
        self.assertEqual(c.transaction_id, 42)
        self.assertEqual(c.last_meter_values["transaction_id"], 42)


class SessionRecordReplayTest(unittest.IsolatedAsyncioTestCase):
    def record(self, tx, energy=5000):
        from custom_components.growatt_thor.sessions.records import (
            parse_growatt_session_record,
        )

        return parse_growatt_session_record(
            "currentrecord",
            f"transactionId={tx}&starttime=2026-10-01 10:00:00&endtime=2026-10-01 11:00:00&"
            f"costenergy={energy}&costmoney=100",
        )

    def make_coordinator(self, data=None):
        c = _build_coordinator(_MemoryStore(data))
        c.hass.async_create_task = lambda coro: coro.close()
        c.runtime_data["append_session_to_csv"] = object()
        return c

    async def test_card_name_is_a_restart_safe_session_snapshot_not_a_later_lookup(
        self,
    ):
        c = self.make_coordinator()
        c._schedule_storage_save = lambda: None
        c.authorization.policy = c.authorization.policy.with_card("00RFID", "Original name")
        c.start_transaction(1, id_tag="00RFID", meter_start=0)
        # A restart during charging must retain the name as it was at start.
        active = self.make_coordinator(c._storage_data())
        await active.async_load_storage()
        active._schedule_storage_save = lambda: None
        active.authorization.policy = active.authorization.policy.with_card(
            "00RFID", "Renamed later"
        )
        active.stop_transaction(transaction_id=1, meter_stop=5000)
        # Another restart before the final vendor record must retain it too.
        completed = self.make_coordinator(active._storage_data())
        await completed.async_load_storage()
        completed.sessions.process_session_record(self.record(2))
        completed.sessions.process_session_record(self.record(1))
        unrelated, original = completed.sessions.outbox.snapshot()
        self.assertEqual(unrelated["authorized_identifier"], "")
        self.assertEqual(unrelated["authorized_alias"], "")
        self.assertEqual(original["authorized_identifier"], "00RFID")
        self.assertEqual(original["authorized_alias"], "Original name")

    async def test_nonconsecutive_replay_after_restart_is_not_applied_twice(self):
        c = self.make_coordinator()
        a, b = self.record(1), self.record(2, 3000)
        c.sessions.process_session_record(a)
        c.sessions.process_session_record(b)
        self.assertEqual(c.total_energy_charged, 8)
        restored = self.make_coordinator(c._storage_data())
        await restored.async_load_storage()
        restored.sessions.process_session_record(a)
        self.assertEqual(restored.total_energy_charged, 8)
        self.assertEqual(restored.last_session_transaction_id, "2")
        self.assertEqual(len(restored.sessions.outbox.snapshot()), 2)

    async def test_replay_with_changed_correlation_keeps_original_history_identity(
        self,
    ):
        c = self.make_coordinator()
        c._schedule_storage_save = lambda: None
        c.start_transaction(1, id_tag="private", meter_start=0)
        c.stop_transaction(transaction_id=1, meter_stop=5000)
        record = self.record(1)
        c.sessions.process_session_record(record)
        rows = c.sessions.outbox.snapshot()
        c.last_completed_transaction = None
        c.sessions.process_session_record(self.record(2, 3000))
        c.sessions.process_session_record(record)
        self.assertEqual(c.total_energy_charged, 8)
        self.assertEqual(c.sessions.outbox.snapshot()[0], rows[0])
        self.assertEqual(len(c.sessions.outbox.snapshot()), 2)

    async def test_restart_between_stop_and_vendor_record_preserves_details(self):
        c = self.make_coordinator()
        c._schedule_storage_save = lambda: None
        c.start_transaction(1, id_tag="RFID", meter_start=100)
        c._active_power_curve = [["2026-10-01T10:01:00Z", 7000]]
        c.site_accounting = coordinator_module.SessionAccumulator("1", meter_start_wh=100)
        c.stop_transaction(transaction_id=1, meter_stop=5100)
        stored = c._storage_data()
        self.assertEqual(len(stored["pending_completed_sessions"]), 1)
        restored = self.make_coordinator(stored)
        await restored.async_load_storage()
        restored.sessions.process_session_record(self.record(1))
        row = restored.sessions.outbox.snapshot()[0]
        self.assertEqual(row["authorized_identifier"], "RFID")
        self.assertEqual(row["session_source"], "home_assistant")
        self.assertIn("7000", row["power_curve"])
        self.assertIn("transaction_stopped", row["events"])
        self.assertEqual(restored.site_accounting_totals["energy_kwh"], 5)
        self.assertIsNone(restored.last_site_accounting)
        self.assertEqual(restored._storage_data()["pending_completed_sessions"], [])

    async def test_multiple_pending_completions_are_bounded_and_match_older_record(
        self,
    ):
        c = self.make_coordinator()
        c._schedule_storage_save = lambda: None
        for tx in range(12):
            c.start_transaction(tx, id_tag=f"RFID-{tx}", meter_start=0)
            c.stop_transaction(transaction_id=tx, meter_stop=5000)
        restored = self.make_coordinator(c._storage_data())
        await restored.async_load_storage()
        self.assertEqual(len(restored.sessions.pending_completions), 10)
        restored.sessions.process_session_record(self.record(2))
        self.assertEqual(restored.sessions.outbox.snapshot()[0]["authorized_identifier"], "RFID-2")
        self.assertEqual(len(restored.sessions.pending_completions), 9)

    async def test_replay_window_is_bounded_and_legacy_last_key_is_migrated(self):
        c = self.make_coordinator()
        for tx in range(55):
            c.sessions.process_session_record(self.record(tx))
        self.assertEqual(len(c._storage_data()["applied_session_record_keys"]), 50)
        data = c._storage_data()
        data.pop("applied_session_record_keys")
        restored = self.make_coordinator(data)
        await restored.async_load_storage()
        restored.sessions.process_session_record(self.record(54))
        self.assertEqual(restored.total_energy_charged, 275)
