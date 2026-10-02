"""Dashboard contract tests without a Home Assistant runtime."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1] / "custom_components" / "growatt_thor"
NAME = "thor_card_test_target"
package = types.ModuleType(NAME)
package.__path__ = [str(ROOT)]
sys.modules[NAME] = package
spec = importlib.util.spec_from_file_location(f"{NAME}.presentation.card_data", ROOT / "presentation/card_data.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def packet(samples):
    return {"meter_values": [{"timestamp": "2026-09-09T12:00:00Z", "sampled_values": samples}]}


def sample(value, phase=None, unit="W", measurand="Power.Active.Import"):
    return {"numeric_value": value, "phase": phase, "unit": unit, "measurand": measurand}


class CardDataTest(unittest.TestCase):
    def test_live_sources_balance_fresh_charger_power_and_disappear_when_stale(self):
        at = "2026-09-22T12:00:00Z"
        coordinator = types.SimpleNamespace(
            last_meter_values={"received_at": at, "meter_values": [{
                "timestamp": at,
                "sampled_values": [sample(3000)],
            }]},
            last_status_notification=None, active_transaction={"start": {"received_at": at}},
            boot_notification=None, source_instance_id="test", charge_point_id="thor",
            transaction_id=2, configuration_values={}, transaction_is_active=True,
            energy=3000, max_current=None, _effective_meter_gap_seconds=lambda: 180,
            external_meter_health="healthy", grid_power=1000,
            external_meter_last_updated_at=at, external_meter_poll_interval=30,
            site_accounting_options={"site_accounting_profile": "pv", "site_grid_source": "thor_external",
                                     "site_solar_power_entity": "sensor.pv", "site_fixed_price": .2},
            hass=types.SimpleNamespace(states={"sensor.pv": types.SimpleNamespace(
                state="2", attributes={"unit_of_measurement": "kW"}, last_updated=at)}),
            now=lambda: at,
        )
        sources = module.dashboard_attributes(coordinator)["power_flow"]["charging_sources"]
        self.assertEqual(sources, {"solar_w": 2000.0, "grid_w": 1000.0,
                                   "battery_w": 0.0, "unknown_w": 0.0})
        coordinator.now = lambda: "2026-09-22T12:05:00Z"
        self.assertNotIn("charging_sources", module.dashboard_attributes(coordinator)["power_flow"])

    def test_active_session_is_prepended_with_live_curve_and_no_invented_cost(self):
        history = {
            "items": [
                {
                    "session_id": f"past-{index}",
                    "active": False,
                    "start_time": f"2026-09-{index + 1:02d}T10:00:00Z",
                }
                for index in range(50)
            ],
            "total_energy_kwh": 42.0,
            "total_cost": 9.5,
            "total_green_energy_kwh": None,
            "total_count": 50,
        }
        coordinator = types.SimpleNamespace(
            transaction_is_active=True,
            active_transaction={
                "start": {
                    "received_at": "2026-09-14T08:00:00Z",
                    "request": {"id_tag": "RFID-LIVE"},
                    "response": {"transaction_id": 23},
                },
                "events": [
                    {
                        "type": "transaction_started",
                        "at": "2026-09-14T08:00:00Z",
                        "source": "ocpp",
                        "certainty": "observed",
                    }
                ],
            },
            transaction_id=23,
            source_instance_id="entry-one",
            charge_point_id="THOR-ONE",
            id_tag="fallback-tag",
            energy=2450,
            _active_power_curve=[
                ["2026-09-14T08:01:00Z", 7100],
                ["2026-09-14T08:02:00Z", 7200],
                ["bad", -1],
            ],
            dashboard_sessions=history,
        )

        data = module.dashboard_sessions(coordinator)

        self.assertEqual(len(data["items"]), 20)
        active = data["items"][0]
        self.assertTrue(active["active"])
        self.assertEqual(active["start_time"], "2026-09-14T08:00:00Z")
        self.assertIsNone(active["end_time"])
        self.assertEqual(active["energy_kwh"], 2.45)
        self.assertIsNone(active["cost"])
        self.assertEqual(active["authorized_identifier"], "RFID-LIVE")
        self.assertEqual(
            active["power_curve"],
            [
                ["2026-09-14T08:01:00Z", 7100.0],
                ["2026-09-14T08:02:00Z", 7200.0],
            ],
        )
        self.assertEqual(active["events"][0]["type"], "transaction_started")
        self.assertEqual(data["total_count"], 50)
        self.assertEqual(data["total_energy_kwh"], 42.0)

    def test_state_payload_budget_drops_completed_details_before_rows(self):
        curve = [
            [f"2026-09-14T08:{minute:02d}:00Z", 7000 + minute]
            for minute in range(60)
        ]
        attributes = {
            "schema": 1,
            "sessions": {
                "items": [
                    {
                        "session_id": f"past-{index}",
                        "active": False,
                        "detail_available": True,
                        "power_curve": curve,
                        "events": [],
                    }
                    for index in range(20)
                ]
            },
        }

        result = module._enforce_card_attribute_budget(attributes)

        self.assertLessEqual(
            module._encoded_size(result),
            module.CARD_ATTRIBUTE_TARGET_BYTES,
        )
        self.assertEqual(len(result["sessions"]["items"]), 20)
        self.assertNotIn("power_curve", result["sessions"]["items"][-1])
        self.assertTrue(result["sessions"]["items"][-1]["detail_available"])

    def test_active_session_can_recover_from_transaction_id_without_start_snapshot(self):
        coordinator = types.SimpleNamespace(
            transaction_is_active=True,
            active_transaction=None,
            transaction_id=24,
            source_instance_id="entry-one",
            charge_point_id="THOR-ONE",
            id_tag=None,
            energy=None,
            _active_power_curve=[],
        )

        active = module.dashboard_active_session(coordinator)

        self.assertTrue(active["active"])
        self.assertIsNone(active["start_time"])
        self.assertIsNone(active["energy_kwh"])
        self.assertTrue(active["session_id"].startswith("ha-"))

    def test_no_active_session_leaves_completed_history_unchanged(self):
        coordinator = types.SimpleNamespace(
            transaction_is_active=False,
            dashboard_sessions={"items": [{"session_id": "past"}], "total_count": 1},
        )

        data = module.dashboard_sessions(coordinator)

        self.assertEqual(data["items"], [{"session_id": "past"}])
        self.assertEqual(data["total_count"], 1)

    def test_power_scale_identity_distinguishes_single_and_three_phase(self):
        for model, phases, power in [("THOR_03AS-S", 1, 3.7), ("THOR_07AS", 1, 7.4), ("THOR_11AS", 3, 11), ("THOR_22AS", 3, 22), ("THOR_44AS", 3, 44)]:
            self.assertEqual(module.charging_power_identity(model), {"nominal_phases": phases, "rated_power_kw": power})
        self.assertIsNone(module.charging_power_identity("unknown")["rated_power_kw"])
        self.assertIsNone(module.charging_power_identity("THOR_07AS", "THOR_22AS")["nominal_phases"])

    def test_authorization_mode_is_safe_reported_configuration_not_policy(self):
        coordinator = types.SimpleNamespace(
            last_meter_values=None, last_status_notification=None,
            active_transaction=None, boot_notification=None, source_instance_id="test",
            configuration_values={}, transaction_is_active=False, energy=None,
            _effective_meter_gap_seconds=lambda: 180, external_meter_health="not_reported",
            grid_power=None, external_meter_last_updated_at=None,
        )
        self.assertIsNone(module.dashboard_attributes(coordinator)["auth_mode"])
        for raw, expected in [("1", "home_assistant_rfid"), ("2", "rfid_only"), ("3", "plug_and_charge"), ("bad", None)]:
            coordinator.configuration_values = {"G_ChargerMode": types.SimpleNamespace(raw_value=raw)}
            result = module.dashboard_attributes(coordinator)
            self.assertEqual(result["auth_mode"], expected)
            self.assertNotIn("authorization", result)
            self.assertNotIn("tag_hashes", result)

    def test_power_flow_preserves_signed_grid_balance_and_pv_allowance(self):
        coordinator = types.SimpleNamespace(
            last_meter_values=None, last_status_notification=None,
            active_transaction=None, boot_notification=None, source_instance_id="test",
            configuration_values={
                "G_SolarLimitPower": types.SimpleNamespace(
                    raw_value="3.96", parsed_value=3.96
                )
            },
            transaction_is_active=False, energy=None, max_current=None,
            _effective_meter_gap_seconds=lambda: 180, external_meter_health="healthy",
            grid_power=-3446, external_meter_last_updated_at="2026-09-09T12:00:00Z",
        )

        self.assertEqual(
            module.dashboard_attributes(coordinator)["power_flow"],
            {
                "received_at": "2026-09-09T12:00:00Z",
                "stale_after_s": 95,
                "grid_w": -3446.0,
                "grid_sign": "positive_import",
                "grid_import_limit_kw": 3.96,
            },
        )

    def test_power_flow_rejects_nonfinite_values(self):
        for value in (float("nan"), float("inf"), "invalid"):
            self.assertIsNone(module._signed_number(value))

    def test_power_flow_includes_configured_normalized_battery_observation(self):
        coordinator = types.SimpleNamespace(
            last_meter_values=None,
            last_status_notification=None,
            active_transaction=None,
            boot_notification=None,
            source_instance_id="test",
            configuration_values={},
            transaction_is_active=False,
            energy=None,
            _effective_meter_gap_seconds=lambda: 180,
            external_meter_health="healthy",
            grid_power=0,
            external_meter_last_updated_at="2026-09-12T10:00:00Z",
            battery_power_entity="sensor.battery_power",
            battery_power_sign="positive_discharge",
            hass=types.SimpleNamespace(
                states={
                    "sensor.battery_power": types.SimpleNamespace(
                        state="1.25",
                        attributes={"unit_of_measurement": "kW"},
                        last_updated="2026-09-12T10:00:01Z",
                    )
                }
            ),
        )

        power_flow = module.dashboard_attributes(coordinator)["power_flow"]
        self.assertEqual(power_flow["battery_w"], 1250)
        self.assertEqual(
            power_flow["battery_received_at"], "2026-09-12T10:00:01Z"
        )
        self.assertEqual(power_flow["battery_sign"], "positive_discharge")

    def test_missing_phases_are_not_zero(self):
        data = module.dashboard_meter_values(packet([sample(12, "L1", "A", "Current.Import")]))
        self.assertEqual(data["currents_a"], [12, None, None])
        self.assertIsNone(data["power_w"])

    def test_units_and_total_power_are_not_double_counted(self):
        data = module.dashboard_meter_values(packet([sample(8.3, unit="kW"), sample(2700, "L1"), sample(2800, "L2"), sample(2800, "L3")]))
        self.assertEqual(data["power_w"], 8300)

    def test_partial_power_is_not_reported_as_total(self):
        self.assertIsNone(module.dashboard_meter_values(packet([sample(2700, "L1")]))["power_w"])
        self.assertEqual(module.dashboard_meter_values(packet([sample(0, "L1"), sample(0, "L2"), sample(0, "L3")]))["power_w"], 0)

    def test_nonfinite_and_unsupported_units_are_missing(self):
        data = module.dashboard_meter_values(packet([sample(float("nan"), "L1", "A", "Current.Import"), sample(12, "L2", "kA", "Current.Import"), sample(float("inf"))]))
        self.assertEqual(data["currents_a"], [None, None, None])
        self.assertIsNone(data["power_w"])

    def test_latest_entry_does_not_retain_prior_phases(self):
        first = packet([sample(12, "L1", "A", "Current.Import")])
        first["meter_values"].append({"timestamp":"later", "sampled_values":[sample(0, "L2", "A", "Current.Import")]})
        self.assertEqual(module.dashboard_meter_values(first)["currents_a"], [None, 0, None])

    def test_unphased_current_is_not_assigned_to_l1(self):
        self.assertEqual(module.dashboard_meter_values(packet([sample(12, None, "A", "Current.Import")]))["currents_a"], [None, None, None])

    def test_empty_packet(self):
        self.assertIsNone(module.dashboard_meter_values(None)["power_w"])


if __name__ == "__main__":
    unittest.main()
