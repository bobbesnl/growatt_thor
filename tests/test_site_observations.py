"""Shared telemetry remains usable without cards, accounting or HA imports."""
import importlib
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace

package = ModuleType("thor_shared_observation_test")
package.__path__ = [str(Path(__file__).parents[1] / "custom_components/growatt_thor")]
sys.modules[package.__name__] = package
site = importlib.import_module(package.__name__ + ".energy.observations")
meter = importlib.import_module(package.__name__ + ".energy.meter_observations")
AT = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


class SiteObservationTest(unittest.TestCase):
    def test_configured_signs_and_units_are_shared(self):
        def state(value, unit):
            return SimpleNamespace(state=str(value), last_updated=AT,
                                   attributes={"unit_of_measurement": unit})
        coordinator = SimpleNamespace(
            hass=SimpleNamespace(states={"sensor.grid": state(-0.002, "MW"),
                                         "sensor.battery": state(-0.3, "kW")}),
            site_accounting_options={"site_grid_source": "ha_sensor",
                                     "site_grid_power_entity": "sensor.grid",
                                     "site_grid_power_sign": "positive_export"},
            battery_power_entity="sensor.battery", battery_power_sign="positive_charge",
        )
        observations = site.read_site_observations(coordinator)
        self.assertEqual(observations.grid.value_at(AT), 2000)
        self.assertEqual(observations.battery.value_at(AT), 300)
        self.assertIsNone(observations.battery.value_at(AT + timedelta(seconds=121)))
        self.assertIsNone(observations.grid.value_at(AT - timedelta(seconds=1)))

    def test_zero_unknown_and_faulted_external_meter_remain_distinct(self):
        self.assertEqual(site.PowerObservation(0, AT).value_at(AT), 0)
        self.assertIsNone(site.PowerObservation(float("nan"), AT).value_at(AT))
        self.assertIsNone(site.PowerObservation(None, AT).value_at(AT))
        coordinator = SimpleNamespace(site_accounting_options={"site_grid_source": "thor_external"},
                                      external_meter_health="faulted", grid_power=1000,
                                      external_meter_last_updated_at=AT)
        self.assertIsNone(site.read_site_observations(coordinator).grid)

    def test_meter_uses_only_latest_packet_and_preserves_missing_phases(self):
        snapshot = {"meter_values": [
            {"timestamp": "old", "sampled_values": [{"numeric_value": 7000,
                 "measurand": "Power.Active.Import", "unit": "W"}]},
            {"timestamp": AT.isoformat(), "sampled_values": [{"numeric_value": 0,
                 "measurand": "Power.Active.Import", "unit": "kW"}]},
        ]}
        result = meter.charging_meter_values(snapshot)
        self.assertEqual(result["power_w"], 0)
        self.assertEqual(result["currents_a"], [None, None, None])
        self.assertEqual(result["sample_at"], AT.isoformat())

    def test_malformed_latest_packet_stays_unknown_without_reusing_old_values(self):
        old = {"timestamp": "old", "sampled_values": [{"numeric_value": 7000,
               "measurand": "Power.Active.Import", "unit": "W"}]}
        for latest in [None, {}, {"sampled_values": None},
                       {"timestamp": 123, "sampled_values": [None, {}, {"phase": []}]}]:
            with self.subTest(latest=latest):
                values = meter.charging_meter_values({"meter_values": [old, latest]})
                self.assertIsNone(values["power_w"])
                self.assertIsNone(values["sample_at"])
                self.assertEqual(values["currents_a"], [None, None, None])
