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
configuration = sys.modules[f'{NAME}.configuration.values']

def mode_values(working='PVlink', solar='1&2'):
    return {key: configuration.configuration_value_from_item(
        {'key': key, 'value': value, 'readonly': False}
    ) for key, value in {'G_WorkingMode': working, 'G_SolarMode': solar}.items()}

AT = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)


def obs(tx=33, *, eligible=True, battery=None, grid=None):
    return core.StopObservation(tx, eligible, battery, grid)


class StopGuardCoreTest(unittest.TestCase):
    def test_default_500_w_three_minutes_and_short_household_load(self):
        tracker = core.StopGuardTracker()
        for seconds in (0, 180, 600):
            self.assertIsNone(tracker.evaluate(AT + timedelta(seconds=seconds), "battery", obs(battery=499)))
        tracker = core.StopGuardTracker()
        value = obs(battery=600)
        tracker.evaluate(AT, "battery", value)
        self.assertIsNone(tracker.evaluate(AT + timedelta(seconds=179), "battery", value))
        self.assertEqual(tracker.evaluate(AT + timedelta(seconds=180), "battery", value), "battery")

    def test_observed_thermomix_interval_does_not_stop_with_new_defaults(self):
        tracker = core.StopGuardTracker()
        for seconds, watts in enumerate((400, 430, 500, 450, 550, 570, 500, 0)):
            value = core.StopObservation(41, True, watts, 0, 8900, 7300)
            self.assertIsNone(tracker.evaluate(AT + timedelta(seconds=seconds * 15), "battery", value))

    def test_pv_covering_ev_gives_bounded_extra_time_not_unlimited_permission(self):
        value = core.StopObservation(33, True, 600, 0, 8900, 7300)
        tracker = core.StopGuardTracker()
        tracker.evaluate(AT, "battery", value)
        self.assertIsNone(tracker.evaluate(AT + timedelta(seconds=180), "battery", value))
        self.assertIsNone(tracker.evaluate(AT + timedelta(seconds=299), "battery", value))
        self.assertEqual(tracker.evaluate(AT + timedelta(seconds=300), "battery", value), "battery")
        # A household load ending during the grace period clears the hold.
        tracker = core.StopGuardTracker()
        tracker.evaluate(AT, "battery", value)
        tracker.evaluate(AT + timedelta(seconds=250), "battery", obs(battery=100))
        self.assertIsNone(tracker.evaluate(AT + timedelta(seconds=301), "battery", value))

    def test_falling_or_missing_pv_keeps_regular_hold(self):
        for solar in (None, float("nan"), 7000):
            tracker = core.StopGuardTracker()
            tracker.evaluate(AT, "battery", core.StopObservation(33, True, 600, 0, 8900, 7300))
            value = core.StopObservation(33, True, 600, 0, solar, 7300)
            self.assertEqual(tracker.evaluate(AT + timedelta(seconds=180), "battery", value), "battery")

    def test_stop_report_restore_rejects_invalid_fields(self):
        report = {"reason": "battery", "at": AT.isoformat(), "threshold_w": 500, "hold_seconds": 300, "observed_w": 600}
        self.assertEqual(core.restore_stop_report(report), report)
        for value in (None, {}, {**report, "reason": "start"}, {**report, "at": "yesterday"}, {**report, "observed_w": float("nan")}):
            self.assertIsNone(core.restore_stop_report(value))

    def test_disabled_and_missing_readings_never_stop(self):
        tracker = core.StopGuardTracker(threshold_w=200, hold_seconds=90)
        self.assertIsNone(tracker.evaluate(AT, "off", obs(battery=3000, grid=3000)))
        self.assertIsNone(tracker.evaluate(AT, "battery_or_grid", obs()))
        self.assertIsNone(tracker.evaluate(AT + timedelta(minutes=5), "battery_or_grid", obs()))

    def test_battery_discharge_sustained_once_per_transaction(self):
        tracker = core.StopGuardTracker(threshold_w=200, hold_seconds=90)
        self.assertIsNone(tracker.evaluate(AT, "battery", obs(battery=250)))
        self.assertIsNone(tracker.evaluate(AT + timedelta(seconds=89), "battery", obs(battery=250)))
        self.assertEqual(tracker.evaluate(AT + timedelta(seconds=90), "battery", obs(battery=250)), "battery")
        self.assertIsNone(tracker.evaluate(AT + timedelta(minutes=3), "battery", obs(battery=250)))
        self.assertIsNone(tracker.evaluate(AT + timedelta(minutes=4), "battery", obs(34, battery=250)))
        self.assertEqual(tracker.evaluate(AT + timedelta(minutes=5, seconds=30), "battery", obs(34, battery=250)), "battery")

    def test_grid_mode_ignores_battery_and_battery_mode_ignores_grid(self):
        tracker = core.StopGuardTracker(threshold_w=200, hold_seconds=90)
        tracker.evaluate(AT, "grid", obs(battery=2000, grid=0))
        self.assertIsNone(tracker.evaluate(AT + timedelta(minutes=2), "grid", obs(battery=2000, grid=0)))
        tracker.evaluate(AT + timedelta(minutes=3), "grid", obs(grid=220))
        self.assertEqual(tracker.evaluate(AT + timedelta(minutes=4, seconds=30), "grid", obs(grid=220)), "grid")
        self.assertIsNone(tracker.evaluate(AT + timedelta(minutes=5), "battery", obs(grid=220)))

    def test_short_cloud_passage_does_not_stop(self):
        tracker = core.StopGuardTracker(threshold_w=200, hold_seconds=90)
        tracker.evaluate(AT, "battery_or_grid", obs(grid=300))
        tracker.evaluate(AT + timedelta(seconds=45), "battery_or_grid", obs(grid=0))
        self.assertIsNone(tracker.evaluate(AT + timedelta(seconds=95), "battery_or_grid", obs(grid=300)))

    def test_ineligible_or_nonfinite_values_clear_hold(self):
        tracker = core.StopGuardTracker(threshold_w=200, hold_seconds=90)
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
                "site_stop_threshold_w": 200, "site_stop_hold_seconds": 90,
                "site_grid_source": "ha_sensor",
                "site_grid_power_entity": "sensor.grid",
                "site_grid_power_sign": "positive_import",
            },
            battery_power_entity="sensor.battery", battery_power_sign="positive_charge",
            transaction_id=33, transaction_is_active=True, connected=True,
            status="charging", configuration_values=mode_values(),
            last_meter_values={
                "transaction_id": 33, "received_at": AT.isoformat(),
                "meter_values": [{
                    "timestamp": AT.isoformat(),
                    "sampled_values": [{"measurand": "Power.Active.Import", "numeric_value": 3000,
                                        "phase": None, "unit": "W"}],
                }],
            },
            _effective_meter_gap_seconds=lambda: 180,
            _schedule_storage_save=lambda: None, async_set_updated_data=lambda _: None,
        )
        self.guard = runtime.EnergyStopGuard(self.hass, self.coordinator)

    def test_observation_uses_confirmed_signs_and_fresh_active_meter(self):
        value = self.guard._observation(AT + timedelta(seconds=30))
        self.assertTrue(value.eligible)
        self.assertEqual(value.battery_discharge_w, 300)
        self.assertEqual(value.grid_import_w, 100)

    def test_pv_grace_uses_fresh_pv_and_current_ev_power(self):
        self.coordinator.site_accounting_options['site_solar_power_entity'] = 'sensor.pv'
        self.states['sensor.pv'] = types.SimpleNamespace(state='4', attributes={'unit_of_measurement': 'kW'}, last_updated=AT)
        value = self.guard._observation(AT)
        self.assertEqual((value.solar_power_w, value.ev_power_w), (4000, 3000))
        self.assertEqual(self.guard.tracker.required_hold(value), 210)
        value = self.guard._observation(AT + timedelta(seconds=121))
        self.assertIsNone(value.solar_power_w)
        self.assertEqual(self.guard.tracker.required_hold(value), 90)

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

    def test_only_confirmed_pv_linkage_plus_is_eligible(self):
        for working, solar, expected in (
            ('PVlink', '1&2', True), ('PVlink', '1&1', False),
            ('Fast', '1&2', False), ('Off Peak', '1&2', False),
            ('invalid', '1&2', False), ('PVlink', 'invalid', False),
        ):
            with self.subTest(working=working, solar=solar):
                self.coordinator.configuration_values = mode_values(working, solar)
                self.assertEqual(self.guard._observation(AT).eligible, expected)
        self.coordinator.configuration_values = {}
        self.assertFalse(self.guard._observation(AT).eligible)
        for profile in ('disabled', 'invalid'):
            self.coordinator.site_accounting_options['site_accounting_profile'] = profile
            self.assertEqual(self.guard.mode(), 'off')

    def test_leaving_pv_plus_clears_hold_before_returning(self):
        self.guard.tracker.evaluate(AT, self.guard.mode(), self.guard._observation(AT))
        self.coordinator.configuration_values = mode_values('Fast')
        at = AT + timedelta(seconds=60)
        self.assertIsNone(self.guard.tracker.evaluate(at, self.guard.mode(), self.guard._observation(at)))
        self.assertIsNone(self.guard.tracker.above_since)
        self.coordinator.configuration_values = mode_values()
        at = AT + timedelta(seconds=90)
        self.assertIsNone(self.guard.tracker.evaluate(at, self.guard.mode(), self.guard._observation(at)))
        self.assertEqual(self.guard.tracker.above_since, at)

    def test_queued_stop_is_cancelled_after_charger_mode_change(self):
        self.guard.tracker.evaluate(AT, self.guard.mode(), self.guard._observation(AT))
        at = AT + timedelta(seconds=90)
        clock = types.SimpleNamespace(now=lambda _tz: at)
        with patch.object(runtime, 'datetime', clock):
            self.assertIsNone(self.guard._still_eligible(33))
            for working, solar in (('Fast', '1&2'), ('PVlink', '1&1'), ('Off Peak', '1&2')):
                self.coordinator.configuration_values = mode_values(working, solar)
                self.assertEqual(self.guard._still_eligible(33), 'auto_stop_no_longer_eligible')

    def test_sustained_battery_flow_invokes_existing_stop_once(self):
        requested = []

        async def press(*, auto_guard, stop_reason):
            self.assertEqual(stop_reason, "energy_guard_battery")
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
        self.assertEqual(self.coordinator.last_energy_stop['reason'], 'battery')
        self.assertEqual(self.coordinator.last_energy_stop['hold_seconds'], 90)


if __name__ == "__main__":
    unittest.main()
