"""Regression tests for the opt-in PV Linkage stop decision and live inputs."""
import asyncio
import importlib.util
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[1] / "custom_components" / "growatt_thor"
NAME = "thor_energy_stop_guard_test_package"
package = types.ModuleType(NAME)
package.__path__ = [str(ROOT)]
sys.modules[NAME] = package


def load(name):
    spec = importlib.util.spec_from_file_location(f"{NAME}.{name}", ROOT / (name.replace(".", "/") + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


core = load('energy.stop_guard')
runtime = load('energy.stop_runtime')
AT = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)


def obs(tx=33, *, eligible=True, battery=None, grid=None):
    return core.StopObservation(tx, eligible, battery, grid)


class StopGuardCoreTest(unittest.TestCase):
    def test_disabled_and_missing_readings_never_stop(self):
        tracker = core.StopGuardTracker()
        self.assertIsNone(tracker.evaluate(AT, "off", obs(battery=3000, grid=3000)))
        self.assertIsNone(tracker.evaluate(AT, "battery_or_grid", obs()))
        self.assertIsNone(tracker.evaluate(AT + timedelta(minutes=5), "battery_or_grid", obs()))

    def test_battery_discharge_sustained_once_per_transaction(self):
        tracker = core.StopGuardTracker()
        self.assertIsNone(tracker.evaluate(AT, "battery", obs(battery=250)))
        self.assertIsNone(tracker.evaluate(AT + timedelta(seconds=89), "battery", obs(battery=250)))
        self.assertEqual(tracker.evaluate(AT + timedelta(seconds=90), "battery", obs(battery=250)), "battery")
        self.assertIsNone(tracker.evaluate(AT + timedelta(minutes=3), "battery", obs(battery=250)))
        self.assertIsNone(tracker.evaluate(AT + timedelta(minutes=4), "battery", obs(34, battery=250)))
        self.assertEqual(tracker.evaluate(AT + timedelta(minutes=5, seconds=30), "battery", obs(34, battery=250)), "battery")

    def test_grid_mode_ignores_battery_and_battery_mode_ignores_grid(self):
        tracker = core.StopGuardTracker()
        tracker.evaluate(AT, "grid", obs(battery=2000, grid=0))
        self.assertIsNone(tracker.evaluate(AT + timedelta(minutes=2), "grid", obs(battery=2000, grid=0)))
        tracker.evaluate(AT + timedelta(minutes=3), "grid", obs(grid=220))
        self.assertEqual(tracker.evaluate(AT + timedelta(minutes=4, seconds=30), "grid", obs(grid=220)), "grid")
        self.assertIsNone(tracker.evaluate(AT + timedelta(minutes=5), "battery", obs(grid=220)))

    def test_short_cloud_passage_does_not_stop(self):
        tracker = core.StopGuardTracker()
        tracker.evaluate(AT, "battery_or_grid", obs(grid=300))
        tracker.evaluate(AT + timedelta(seconds=45), "battery_or_grid", obs(grid=0))
        self.assertIsNone(tracker.evaluate(AT + timedelta(seconds=95), "battery_or_grid", obs(grid=300)))

    def test_ineligible_or_nonfinite_values_clear_hold(self):
        tracker = core.StopGuardTracker()
        tracker.evaluate(AT, "battery", obs(battery=300))
        tracker.evaluate(AT + timedelta(seconds=60), "battery", obs(eligible=False, battery=300))
        self.assertIsNone(tracker.evaluate(AT + timedelta(seconds=95), "battery", obs(battery=300)))
        self.assertIsNone(tracker.evaluate(AT + timedelta(seconds=190), "battery", obs(battery=float("nan"))))


class StopGuardRuntimeTest(unittest.TestCase):
    def setUp(self):
        def state(value, unit, updated=AT):
            return types.SimpleNamespace(
                state=str(value), attributes={"unit_of_measurement": unit}, last_updated=updated,
            )
        self.states = {
            "sensor.grid": state(0.1, "kW"),
            "sensor.battery": state(-0.3, "kW"),
        }
        self.hass = types.SimpleNamespace(states=self.states, data={})
        self.coordinator = types.SimpleNamespace(
            hass=self.hass,
            site_accounting_options={
                "site_accounting_profile": "pv_battery",
                "site_auto_stop_mode": "battery_or_grid",
                "site_grid_source": "ha_sensor",
                "site_grid_power_entity": "sensor.grid",
                "site_grid_power_sign": "positive_import",
            },
            battery_power_entity="sensor.battery", battery_power_sign="positive_charge",
            transaction_id=33, transaction_is_active=True, connected=True,
            status="charging", configuration_values={},
            last_meter_values={
                "transaction_id": 33, "received_at": AT.isoformat(),
                "meter_values": [{
                    "timestamp": AT.isoformat(),
                    "sampled_values": [{"measurand": "Power.Active.Import", "numeric_value": 3000,
                                        "phase": None, "unit": "W"}],
                }],
            },
            _effective_meter_gap_seconds=lambda: 180,
        )
        self.guard = runtime.EnergyStopGuard(self.hass, self.coordinator)

    def test_observation_uses_confirmed_signs_and_fresh_active_meter(self):
        value = self.guard._observation(AT + timedelta(seconds=30))
        self.assertTrue(value.eligible)
        self.assertEqual(value.battery_discharge_w, 300)
        self.assertEqual(value.grid_import_w, 100)

    def test_wire_status_and_enum_use_the_same_charging_state(self):
        for status in ("Charging", "charging", types.SimpleNamespace(value="Charging")):
            self.coordinator.status = status
            self.assertTrue(self.guard._observation(AT).eligible)
        self.coordinator.status = "SuspendedEV"
        self.assertFalse(self.guard._observation(AT).eligible)

    def test_stale_unavailable_and_wrong_transaction_fail_closed(self):
        self.assertIsNone(self.guard._observation(AT + timedelta(seconds=130)).battery_discharge_w)
        self.states["sensor.battery"].state = "unavailable"
        self.assertIsNone(self.guard._observation(AT).battery_discharge_w)
        self.coordinator.last_meter_values["transaction_id"] = 34
        self.assertFalse(self.guard._observation(AT).eligible)

    def test_every_charger_mode_can_stop_but_disabled_profile_cannot(self):
        self.coordinator.configuration_values = {"G_WorkingMode": "fast"}
        self.assertTrue(self.guard._observation(AT).eligible)
        self.coordinator.site_accounting_options["site_accounting_profile"] = "disabled"
        self.assertEqual(self.guard.mode(), "off")
        self.coordinator.site_accounting_options["site_accounting_profile"] = "invalid"
        self.assertEqual(self.guard.mode(), "off")

    def test_sustained_battery_flow_invokes_existing_stop_once(self):
        requested = []

        async def press(*, auto_guard):
            requested.append(auto_guard())

        self.guard.stop_command = types.SimpleNamespace(async_request=press)
        self.assertEqual(self.hass.data, {})
        moments = iter((AT, AT + timedelta(seconds=90), AT + timedelta(seconds=90)))
        clock = types.SimpleNamespace(now=lambda _tz: next(moments))
        sleeps = 0

        async def sleep(_seconds):
            nonlocal sleeps
            sleeps += 1
            if sleeps == 2:
                raise asyncio.CancelledError

        with patch.object(runtime, "datetime", clock), \
             patch.object(runtime.asyncio, "sleep", sleep):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(self.guard._run())
        self.assertEqual(requested, [None])


if __name__ == "__main__":
    unittest.main()
