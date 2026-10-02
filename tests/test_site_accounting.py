"""Scenario tests for the HA-independent accounting core and checkpoint."""
import importlib.util
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1] / "custom_components" / "growatt_thor"
NAME = "thor_site_accounting_test_package"
package = types.ModuleType(NAME)
package.__path__ = [str(ROOT)]
sys.modules[NAME] = package


def load(name):
    spec = importlib.util.spec_from_file_location(f"{NAME}.{name}", ROOT / (name.replace(".", "/") + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


load('energy.sources')
currency = load('energy.currency')
core = load('energy.accounting')
runtime = load('energy.accounting_runtime')
AT = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)


def observation(watts, at=AT):
    return core.PowerObservation(watts, at)


def delta(kwh=1, start=None, end=AT):
    return core.EVEnergyDelta("site", "charger", "tx", start or end - timedelta(hours=1), end, kwh)


class SiteAccountingTest(unittest.TestCase):
    def price_from_sensor(self, value="0.313922", *, attributes=None, updated=None, fixed=None):
        state = types.SimpleNamespace(
            state=value,
            attributes={"unit_of_measurement": "€/kWh", **(attributes or {})},
            last_updated=updated or AT - timedelta(days=3),
        )
        coordinator = types.SimpleNamespace(
            hass=types.SimpleNamespace(config=types.SimpleNamespace(currency="EUR"), states={"sensor.price": state}),
            site_accounting_options={"site_accounting_profile": "grid_only", "site_tariff_entity": "sensor.price", "site_fixed_price": fixed},
            battery_power_entity=None,
        )
        return runtime.site_inputs(coordinator, AT)[1]

    def test_unchanged_current_price_remains_valid_after_one_hour(self):
        tariff = self.price_from_sensor()
        self.assertEqual(tariff.price_at(AT), 0.313922)
        result = core.allocate(delta(), core.SiteObservations(), tariff, core.AccountingPolicy())
        self.assertEqual(result.effective_grid_cost, 0.313922)

    def test_sensor_price_preserves_unavailable_invalid_and_restored_states(self):
        for value in ("unknown", "unavailable", "nan", "inf", "", None):
            with self.subTest(value=value):
                self.assertIsNone(self.price_from_sensor(value, fixed=.25).price_at(AT))
        for attributes in ({"unit_of_measurement": "ct/kWh"}, {"restored": True}):
            self.assertIsNone(self.price_from_sensor(attributes=attributes).price_at(AT))
        self.assertEqual(self.price_from_sensor("-0.15").price_at(AT), -.15)
        self.assertEqual(self.price_from_sensor("0").price_at(AT), 0)

    def test_tariff_validity_uses_exclusive_end_and_rejects_bad_bounds(self):
        for bounds in (
            {"valid_to": AT.isoformat()},
            {"valid_from": (AT + timedelta(seconds=1)).isoformat()},
            {"valid_to": "not a date"},
            {"valid_to": "2026-09-22T13:00:00"},
            {"valid_from": AT.isoformat(), "valid_to": (AT - timedelta(seconds=1)).isoformat()},
        ):
            with self.subTest(bounds=bounds):
                self.assertIsNone(self.price_from_sensor(attributes=bounds).price_at(AT))
        self.assertEqual(self.price_from_sensor(attributes={
            "valid_from": (AT - timedelta(days=100)).isoformat(),
            "valid_to": (AT + timedelta(days=100)).isoformat(),
        }).price_at(AT), .313922)

    def test_timeslot_expiry_overrides_a_long_running_tariff_agreement(self):
        bounds = {
            "valid_from": (AT - timedelta(days=100)).isoformat(),
            "valid_to": (AT + timedelta(days=100)).isoformat(),
            "active_timeslot_from": (AT - timedelta(minutes=15)).isoformat(),
            "active_timeslot_to": AT.isoformat(),
        }
        self.assertIsNone(self.price_from_sensor(attributes=bounds).price_at(AT))
        bounds["active_timeslot_to"] = (AT + timedelta(minutes=15)).isoformat()
        self.assertEqual(self.price_from_sensor(attributes=bounds).price_at(AT), .313922)

    def test_new_price_cannot_be_used_for_earlier_energy_deltas(self):
        tariff = self.price_from_sensor(updated=AT + timedelta(seconds=1))
        self.assertIsNone(tariff.price_at(AT))
        self.assertIsNone(core.Tariff(.2, observed_at=AT - timedelta(hours=2)).price_at(AT))

    def test_price_unit_normalizes_euro_symbol_without_currency_conversion(self):
        self.assertEqual(currency.normalized_price_unit("€/kWh", "EUR"), "EUR/kWh")
        self.assertEqual(currency.normalized_price_unit(" EUR/kWh ", "EUR"), "EUR/kWh")
        self.assertIsNone(currency.normalized_price_unit("€/kWh", "USD"))
        self.assertIsNone(currency.normalized_price_unit("ct/kWh", "EUR"))

    def test_symbol_price_sensor_is_sampled_with_current_unit_validation(self):
        state = types.SimpleNamespace(
            state="-0.05", attributes={"unit_of_measurement": "€/kWh"}, last_updated=AT,
        )
        coordinator = types.SimpleNamespace(
            hass=types.SimpleNamespace(config=types.SimpleNamespace(currency="EUR"), states={"sensor.price": state}),
            site_accounting_options={"site_accounting_profile": "grid_only", "site_tariff_entity": "sensor.price"},
            battery_power_entity=None,
        )
        self.assertEqual(runtime.site_inputs(coordinator, AT)[1].price_at(AT), -0.05)
        state.attributes["unit_of_measurement"] = "ct/kWh"
        self.assertIsNone(runtime.site_inputs(coordinator, AT)[1].price_at(AT))

    def test_live_battery_source_change_uses_current_entity_and_sign(self):
        state = types.SimpleNamespace(
            state="-0.5", attributes={"unit_of_measurement": "kW"}, last_updated=AT,
        )
        coordinator = types.SimpleNamespace(
            hass=types.SimpleNamespace(states={"sensor.new_battery": state}),
            site_accounting_options={"site_accounting_profile": "pv_battery",
                                     "battery_power_entity": "sensor.old_battery"},
            battery_power_entity="sensor.new_battery", battery_power_sign="positive_charge",
        )
        site = runtime.site_inputs(coordinator, AT)[0]
        self.assertEqual(site.battery.value_at(AT), 500)

    def test_cumulative_coverage_preserves_unknown(self):
        self.assertIsNone(runtime.coverage_percent({"energy_kwh": 0, "unknown_kwh": 0}))
        self.assertEqual(runtime.coverage_percent({"energy_kwh": 2, "unknown_kwh": .5}), 75.0)

    def test_ha_sensor_units_sign_and_external_meter_health(self):
        def state(value, unit):
            return types.SimpleNamespace(state=str(value), attributes={"unit_of_measurement": unit}, last_updated=AT)
        coordinator = types.SimpleNamespace(
            hass=types.SimpleNamespace(states={"sensor.grid": state(-.002, "MW"),
                                              "sensor.pv": state(3, "kW")}),
            site_accounting_options={"site_accounting_profile": "pv",
                                     "site_grid_source": "ha_sensor",
                                     "site_grid_power_entity": "sensor.grid",
                                     "site_grid_power_sign": "positive_export",
                                     "site_solar_power_entity": "sensor.pv",
                                     "site_fixed_price": -.1},
            external_meter_health="faulted", grid_power=9999,
            external_meter_last_updated_at=AT,
            battery_power_entity=None,
        )
        site, tariff, policy = runtime.site_inputs(coordinator, AT)
        self.assertEqual(site.grid.value_at(AT), 2000)
        self.assertEqual(site.solar.value_at(AT), 3000)
        self.assertEqual(tariff.price_at(AT), -.1)
        coordinator.site_accounting_options["site_grid_source"] = "thor_external"
        self.assertIsNone(runtime.site_inputs(coordinator, AT)[0].grid)

    def test_grid_only_fixed_tariff(self):
        result = core.allocate(delta(), core.SiteObservations(), core.Tariff(.3), core.AccountingPolicy())
        self.assertEqual((result.direct_grid, result.unknown, result.effective_grid_cost), (1, 0, .3))
        self.assertEqual(result.data_quality.quality, "declared")

    def test_pv_zero_import(self):
        site = core.SiteObservations(grid=observation(0), solar=observation(3000))
        result = core.allocate(delta(), site, core.Tariff(.2), core.AccountingPolicy(topology="pv"))
        self.assertEqual((result.direct_solar, result.direct_grid, result.unknown), (1, 0, 0))

    def test_grid_first_respects_measured_house_load(self):
        site = core.SiteObservations(grid=observation(0), solar=observation(3000),
                                     household=observation(2000))
        result = core.allocate(delta(2), site, core.Tariff(.2),
                               core.AccountingPolicy(topology="pv"))
        self.assertEqual((result.direct_solar, result.unknown), (1, 1))

    def test_simultaneous_house_load_and_load_first_order(self):
        site = core.SiteObservations(grid=observation(0), solar=observation(6000),
                                     household=observation(2000), battery=observation(-3000),
                                     thermal=observation(1000))
        policy = core.AccountingPolicy("load_first", topology="pv_battery")
        result = core.allocate(delta(2), site, core.Tariff(.2), policy)
        self.assertEqual((result.direct_solar, result.unknown), (1, 1))
        self.assertEqual(result.policy_id, "load_first")
        self.assertEqual(result.policy_version, 1)

    def test_direct_measurement_overrides_priority(self):
        site = core.SiteObservations(grid=observation(0), solar=observation(7000),
                                     household=observation(1000), direct_grid=observation(500))
        result = core.allocate(delta(), site, core.Tariff(.2), core.AccountingPolicy("load_first", topology="pv"))
        self.assertEqual(result.direct_grid, .5)
        self.assertEqual(result.direct_solar, .5)

    def test_cloud_passage_short_grid_import(self):
        site = core.SiteObservations(grid=observation(2000), solar=observation(4000))
        result = core.allocate(delta(1, AT - timedelta(minutes=15)), site,
                               core.Tariff(.2), core.AccountingPolicy(topology="pv"))
        self.assertEqual((result.direct_grid, result.direct_solar), (.5, .5))

    def test_battery_discharge_is_not_green(self):
        site = core.SiteObservations(grid=observation(0), solar=observation(0), battery=observation(1000))
        result = core.allocate(delta(), site, core.Tariff(.2), core.AccountingPolicy(topology="pv_battery"))
        self.assertEqual((result.battery_unknown, result.direct_solar), (1, 0))

    def test_stale_missing_unavailable_remain_unknown(self):
        stale = observation(0, AT - timedelta(hours=2))
        site = core.SiteObservations(grid=stale, solar=observation(3000))
        result = core.allocate(delta(), site, core.Tariff(.2), core.AccountingPolicy(topology="pv"))
        self.assertEqual((result.unknown, result.data_quality.coverage), (1, 0))
        self.assertIn("grid", result.data_quality.missing)
        missing = core.allocate(delta(), core.SiteObservations(), core.Tariff(None), core.AccountingPolicy(topology="pv"))
        self.assertEqual(missing.unknown, 1)

    def test_tariff_change_and_negative_price(self):
        session = runtime.SessionAccumulator("tx", last_meter_wh=0, last_meter_at=AT - timedelta(hours=2))
        site = core.SiteObservations()
        for index, price in enumerate((.4, -.1)):
            at = AT - timedelta(hours=1-index)
            self.assertTrue(session.observe(meter_wh=(index+1)*1000, at=at,
                site_id="site", charger_id="charger",
                inputs=(site, core.Tariff(price), core.AccountingPolicy())))
        self.assertAlmostEqual(session.effective_grid_cost, .3)
        self.assertAlmostEqual(sum(session.buckets.values()), 2)
        self.assertEqual(session.as_session_dict()["accounting_quality"], "declared")

    def test_duplicates_order_reset_and_begin_do_not_count(self):
        session = runtime.SessionAccumulator("tx", last_meter_wh=1000, last_meter_at=AT)
        params = dict(site_id="site", charger_id="charger", inputs=None)
        self.assertFalse(session.observe(meter_wh=9000, at=AT + timedelta(minutes=1), context="Transaction.Begin", **params))
        self.assertTrue(session.observe(meter_wh=1500, at=AT + timedelta(minutes=1), **params))
        self.assertFalse(session.observe(meter_wh=1500, at=AT + timedelta(minutes=1), **params))
        self.assertFalse(session.observe(meter_wh=1300, at=AT + timedelta(seconds=30), **params))
        self.assertFalse(session.observe(meter_wh=10, at=AT + timedelta(minutes=2), **params))
        self.assertEqual(session.reset_count, 1)
        self.assertTrue(session.observe(meter_wh=510, at=AT + timedelta(minutes=3), **params))
        self.assertEqual(session.buckets["unknown"], 1)

    def test_checkpoint_restart_and_reconciliation(self):
        session = runtime.SessionAccumulator("tx", meter_start_wh=0, last_meter_wh=0, last_meter_at=AT)
        session.observe(meter_wh=1000, at=AT + timedelta(hours=1), site_id="site", charger_id="charger",
                        inputs=(core.SiteObservations(), core.Tariff(.2), core.AccountingPolicy()))
        restored = runtime.SessionAccumulator.from_dict(session.as_dict())
        self.assertFalse(restored.observe(meter_wh=1000, at=AT + timedelta(hours=1),
                                          site_id="site", charger_id="charger", inputs=None))
        restored.reconcile(1.2)
        self.assertAlmostEqual(restored.buckets["unknown"], .2)
        self.assertIsNone(restored.as_session_dict()["green_energy_kwh"])

    def test_invalid_checkpoint_cost_remains_unknown(self):
        for value in ("invalid", "nan", "inf", "-inf"):
            with self.subTest(value=value):
                restored = runtime.SessionAccumulator.from_dict({
                    "transaction_id": "tx", "effective_grid_cost": value,
                })
                self.assertIsNone(restored.as_session_dict()["effective_grid_cost"])
                self.assertEqual(restored.effective_grid_cost, 0)

    def test_checkpoint_without_timestamp_reestablishes_meter_baseline(self):
        restored = runtime.SessionAccumulator.from_dict({
            "transaction_id": "tx", "last_meter_wh": 1000,
            "buckets": {"direct_grid": 1},
        })
        params = dict(site_id="site", charger_id="charger", inputs=None)
        self.assertFalse(restored.observe(meter_wh=2000, at=AT, **params))
        self.assertTrue(restored.observe(meter_wh=2500, at=AT + timedelta(minutes=1), **params))
        self.assertEqual(restored.buckets["direct_grid"], 1)
        self.assertEqual(restored.buckets["unknown"], .5)

    def test_power_fallback_is_separate_and_bounded(self):
        session = runtime.SessionAccumulator("tx")
        self.assertFalse(session.observe_power_fallback(3600, AT))
        self.assertTrue(session.observe_power_fallback(3600, AT + timedelta(minutes=5)))
        self.assertAlmostEqual(session.power_fallback_kwh, .3)
        self.assertEqual(sum(session.buckets.values()), 0)
        restored = runtime.SessionAccumulator.from_dict(session.as_dict())
        self.assertAlmostEqual(restored.power_fallback_kwh, .3)
        self.assertFalse(restored.observe_power_fallback(3600, AT + timedelta(minutes=11)))
        self.assertAlmostEqual(restored.power_fallback_kwh, .3)

    def test_parallel_evse_split_conserves_site_energy(self):
        d1, d2 = delta(1), core.EVEnergyDelta("site", "charger2", "tx2", AT-timedelta(hours=1), AT, 2)
        total = core.allocate(delta(3), core.SiteObservations(grid=observation(1000), solar=observation(2000)),
                              core.Tariff(.3), core.AccountingPolicy(topology="pv"))
        first, second = core.split_parallel(total, (d1, d2))
        self.assertAlmostEqual(first.direct_grid + second.direct_grid, total.direct_grid)
        self.assertAlmostEqual(first.direct_solar + second.direct_solar, total.direct_solar)
        self.assertAlmostEqual(first.direct_solar + first.direct_grid + first.unknown, 1)
        self.assertAlmostEqual(second.direct_solar + second.direct_grid + second.unknown, 2)


if __name__ == "__main__":
    unittest.main()
