"""Pure site-option validation and entry-scoped live updates."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from tests.support import build_coordinator, load_package_module

options = load_package_module("energy.site_options")


def draft(**changes):
    return {
        "site_accounting_profile": "grid_only",
        "site_grid_source": "thor_external",
        "site_grid_power_sign": "positive_import",
        "site_fixed_price": 0.25,
        **changes,
    }


class SiteOptionsTest(unittest.TestCase):
    def test_valid_grid_draft_requires_no_ha_runtime(self):
        self.assertEqual(options.validate_site_options(draft(), {}, {}), {})

    def test_stop_range_limits_and_finite_values_are_preserved(self):
        for value in (99, 10001, float("nan"), float("inf"), "500"):
            with self.subTest(value=value):
                errors = options.validate_site_options(draft(site_stop_threshold_w=value), {}, {})
                self.assertEqual(errors, {"site_stop_threshold_w": "invalid_stop_settings"})

    def test_duplicate_battery_source_marks_the_new_assignment(self):
        states = {"sensor.battery": SimpleNamespace(attributes={"unit_of_measurement": "W"})}
        errors = options.validate_site_options(
            draft(site_grid_source="ha_sensor", site_grid_power_entity="sensor.battery"),
            {"battery_power_entity": "sensor.battery"},
            states,
        )
        self.assertEqual(errors, {"site_grid_power_entity": "duplicate_power_source"})

    def test_tariffs_use_the_explicit_installation_currency(self):
        states = {"sensor.tariff": SimpleNamespace(attributes={"unit_of_measurement": "USD/kWh"})}
        value = draft(site_tariff_entity="sensor.tariff")
        self.assertEqual(options.validate_site_options(value, {}, states, currency="USD"), {})
        self.assertEqual(
            options.validate_site_options(value, {}, states, currency="EUR"),
            {"site_tariff_entity": "invalid_tariff_sensor"},
        )

    def test_missing_battery_keeps_profile_and_stop_errors_distinct(self):
        errors = options.validate_site_options(
            draft(site_accounting_profile="pv_battery", site_auto_stop_mode="battery"), {}, {}
        )
        self.assertEqual(
            errors,
            {
                "site_accounting_profile": "profile_requires_battery",
                "site_auto_stop_mode": "auto_stop_requires_battery",
            },
        )


class LiveOptionsTest(unittest.IsolatedAsyncioTestCase):
    async def test_only_site_saves_refresh_the_owning_guard(self):
        coordinator = build_coordinator()
        refresh = Mock()
        coordinator.runtime_data["energy_stop_guard"] = SimpleNamespace(refresh=refresh)
        await coordinator.async_apply_options(
            {"location": "Garage", "poll_interval": 45}, section="general"
        )
        await coordinator.async_apply_options(
            {"battery_power_entity": "sensor.battery", "battery_power_sign": "positive_charge"},
            section="energy_sources",
        )
        refresh.assert_not_called()
        saved = draft()
        await coordinator.async_apply_options(saved, section="site_accounting")
        refresh.assert_called_once_with()
        self.assertEqual(coordinator.location, "Garage")
        self.assertEqual(coordinator.external_meter_poll_interval, 45)
        self.assertEqual(coordinator.battery_power_entity, "sensor.battery")
        self.assertEqual(coordinator.battery_power_sign, "positive_charge")
        self.assertEqual(coordinator.site_accounting_options, saved)
        self.assertIsNot(coordinator.site_accounting_options, saved)
