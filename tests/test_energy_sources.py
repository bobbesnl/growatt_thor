"""Test optional Home Assistant energy-source normalization."""
import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
    / "energy/sources.py"
)
SPEC = importlib.util.spec_from_file_location("thor_energy_sources_test_target", MODULE_PATH)
energy_sources = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(energy_sources)


def state(value, unit, name, *, updated=None):
    return SimpleNamespace(
        state=value,
        attributes={"unit_of_measurement": unit, "friendly_name": name},
        last_updated=updated,
    )


class EnergySourcesTest(unittest.TestCase):
    def test_power_candidates_filter_units_and_rank_battery_names_first(self):
        states = {
            "sensor.pv_power": state("4200", "W", "PV power"),
            "sensor.storage_flow": state("700", "W", "House storage"),
            "sensor.home_battery_power": state("1.5", "kW", "Home battery power"),
            "sensor.battery_combined_power": state(
                "-900", "W", "Battery combined power"
            ),
            "sensor.battery_energy": state("8", "kWh", "Battery energy"),
            "switch.battery_power": state("1", "W", "Battery switch"),
        }

        self.assertEqual(
            [option["value"] for option in energy_sources.power_sensor_options(states)],
            [
                "",
                "sensor.battery_combined_power",
                "sensor.home_battery_power",
                "sensor.storage_flow",
                "sensor.pv_power",
            ],
        )

    def test_configured_missing_sensor_remains_selectable_for_repair(self):
        options = energy_sources.power_sensor_options({}, "sensor.old_battery")
        self.assertEqual(options[-1]["value"], "sensor.old_battery")

    def test_solar_ranking_and_conflicting_current_selection_remain_repairable(self):
        states = {
            "sensor.battery": state("800", "W", "Battery combined power"),
            "sensor.pv": state("5000", "W", "PV generation"),
        }
        options = energy_sources.power_sensor_options(states, role="solar")
        self.assertEqual(options[1]["value"], "sensor.pv")
        options = energy_sources.power_sensor_options(
            states, "sensor.battery", role="solar", exclude={"sensor.battery"},
        )
        self.assertIn("sensor.battery", [item["value"] for item in options])
        states["sensor.battery"].attributes["unit_of_measurement"] = "kWh"
        options = energy_sources.power_sensor_options(states, "sensor.battery")
        self.assertIn("sensor.battery", [item["value"] for item in options])

    def test_power_candidates_accept_home_assistant_state_machine(self):
        battery = state("1.5", "kW", "Home battery power")
        battery.entity_id = "sensor.home_battery_power"
        states = SimpleNamespace(async_all=lambda: [battery])

        options = energy_sources.power_sensor_options(states)

        self.assertEqual(
            [option["value"] for option in options],
            ["", "sensor.home_battery_power"],
        )

    def test_power_normalizes_supported_units_and_rejects_invalid_states(self):
        self.assertEqual(energy_sources.power_w(state("1.25", "kW", "Battery")), 1250)
        self.assertEqual(energy_sources.power_w(state("0.002", "MW", "Battery")), 2000)
        self.assertIsNone(energy_sources.power_w(state("unknown", "W", "Battery")))
        self.assertIsNone(energy_sources.power_w(state("2", "kWh", "Battery")))

    def test_battery_flow_uses_one_documented_positive_discharge_contract(self):
        updated = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
        battery = state("1.5", "kW", "Battery", updated=updated)
        coordinator = SimpleNamespace(
            hass=SimpleNamespace(states={"sensor.battery": battery}),
            battery_power_entity="sensor.battery",
            battery_power_sign=energy_sources.BATTERY_POSITIVE_DISCHARGE,
        )
        self.assertEqual(
            energy_sources.battery_power_attributes(coordinator),
            {
                "battery_w": 1500,
                "battery_received_at": "2026-09-12T10:00:00Z",
                "battery_sign": "positive_discharge",
            },
        )
        coordinator.battery_power_sign = energy_sources.BATTERY_POSITIVE_CHARGE
        self.assertEqual(
            energy_sources.battery_power_attributes(coordinator)["battery_w"], -1500
        )
        coordinator.battery_power_entity = None
        self.assertEqual(energy_sources.battery_power_attributes(coordinator), {})


if __name__ == "__main__":
    unittest.main()
