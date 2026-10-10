"""Exercise real THOR wall-clock samples through all live energy consumers."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

from test_write_queue import coordinator_module
from custom_components.growatt_thor.energy.stop_runtime import EnergyStopGuard
from custom_components.growatt_thor.configuration.values import configuration_value_from_item
from custom_components.growatt_thor.presentation.card_data import dashboard_attributes

AT = datetime(2026, 10, 2, 14, 52, 49, tzinfo=timezone.utc)


class MeterTimeIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.at = AT
        def state(value):
            return SimpleNamespace(state=str(value), attributes={"unit_of_measurement": "W"}, last_updated=AT)
        self.c = c = coordinator_module.GrowattCoordinator.__new__(coordinator_module.GrowattCoordinator)
        c.hass = SimpleNamespace(
            config=SimpleNamespace(time_zone="Europe/Berlin", currency="EUR"),
            states={"sensor.pv": state(6000), "sensor.battery": state(-2000)},
            data={}, async_create_task=lambda coro: coro.close(),
        )
        c.now = lambda: self.at.isoformat()
        c.async_set_updated_data = lambda _: None
        c._schedule_storage_save = lambda: None
        async def save():
            pass
        c.async_save_storage = save
        c.transaction_id = 27
        c.active_transaction = {"start": {"received_at": AT.isoformat(), "response": {"transaction_id": 27}}}
        c.status = "Charging"
        c.connected = True
        c.source_instance_id = "test"
        c.charge_point_id = "thor"
        c.configuration_values = {
            key: configuration_value_from_item({"key": key, "value": value, "readonly": False})
            for key, value in {"G_WorkingMode": "PVlink", "G_SolarMode": "1&2"}.items()
        }
        c.last_status_notification = None
        c.boot_notification = None
        c.pv_boost_mode_draft = None
        c.last_charger_fault = None
        c.max_current = None
        c.energy = 1000
        c.power = None
        c.phase_power = {}
        c.currents = {}
        c.voltages = {}
        c._active_power_curve = []
        c._session_event_tracker = None
        c.effective_charging = coordinator_module.EffectiveChargingTracker()
        c.external_meter_faulted = False
        c.meterval_consecutive_timeouts = 0
        c.external_meter_poll_interval = 30
        c.external_meter_last_updated_at = AT.isoformat()
        c.grid_power = 0
        c.battery_power_entity = "sensor.battery"
        c.battery_power_sign = "positive_charge"
        c.site_accounting_options = {
            "site_accounting_profile": "pv_battery", "site_auto_stop_mode": "battery",
            "site_stop_threshold_w": 200, "site_stop_hold_seconds": 90,
            "site_grid_source": "thor_external", "site_solar_power_entity": "sensor.pv", "site_fixed_price": .3,
        }
        c.site_accounting = coordinator_module.SessionAccumulator(
            transaction_id="27", last_meter_wh=1000, last_meter_at=AT - timedelta(seconds=30),
        )
        self.guard = EnergyStopGuard(c.hass, c)

    def receive(self, timestamp="2026-10-02T16:52:49", energy=1050):
        self.c.process_meter_values([{"timestamp": timestamp, "sampledValue": [
            {"value": "7000", "measurand": "Power.Active.Import", "unit": "W"},
            {"value": str(energy), "measurand": "Energy.Active.Import.Register", "unit": "Wh"},
        ]}], transaction_id=27)

    def test_confirmed_new_session_clears_and_persists_protection_notice(self):
        self.receive()
        c = self.c
        c.last_energy_stop = {"reason": "battery", "at": AT.isoformat()}
        c._pending_plugged_event = None
        c.sessions = coordinator_module.SessionLifecycle(c)
        saved_notices = []
        c._schedule_storage_save = lambda: saved_notices.append(c.last_energy_stop)
        c.start_transaction(28, connector_id=1, meter_start=1050)
        self.assertIsNone(c.last_energy_stop)
        self.assertEqual(saved_notices, [None])
        self.assertIsNone(dashboard_attributes(c)["energy_stop"])
        self.assertEqual(c.transaction_id, 28)

    def test_status_notification_persists_session_pause_without_meter_sample(self):
        c = self.c
        tracker = c._session_event_tracker = coordinator_module.SessionEventTracker.start(AT.isoformat())
        c.active_transaction["start"]["request"] = {"connector_id": 1}
        c.active_transaction["events"] = tracker.events
        self.receive()
        curve = list(c._active_power_curve)
        saved = []
        c._schedule_storage_save = lambda: saved.append(True)
        self.at += timedelta(minutes=5)
        for connector in (0, 2):
            c.record_status_notification(connector, "SuspendedEV", "NoError")
        self.assertFalse(saved)
        c.record_status_notification(1, "SuspendedEV", "NoError")
        self.assertEqual(saved, [True])
        self.assertEqual(c.active_transaction["events"][-1]["reason"], "suspended_ev")
        self.assertEqual(c.active_transaction["events"][-1]["at"], self.at.isoformat())
        self.assertEqual(c._active_power_curve, curve)
        self.assertEqual(c.transaction_id, 27)
        c.record_status_notification(1, "SuspendedEV", "NoError")
        self.assertEqual(saved, [True])

    def test_local_sample_reaches_gauge_accounting_curve_and_stop_guard(self):
        self.receive()
        packet = self.c.last_meter_values["meter_values"][0]
        self.assertEqual(packet["timestamp"], "2026-10-02T14:52:49Z")
        self.assertEqual(packet["raw"]["timestamp"], "2026-10-02T16:52:49")
        sources = dashboard_attributes(self.c)["power_flow"]["charging_sources"]
        self.assertAlmostEqual(sources["battery_w"], 2000)
        self.assertAlmostEqual(sources["solar_w"], 5000)
        self.assertAlmostEqual(sum(sources.values()), 7000)
        self.assertGreater(self.c.site_accounting.buckets["battery_unknown"], 0)
        self.assertAlmostEqual(sum(self.c.site_accounting.buckets.values()), .05)
        self.assertEqual(self.c._active_power_curve[-1][0], "2026-10-02T14:52:49Z")
        observation = self.guard._observation(AT)
        self.assertTrue(observation.eligible)
        self.assertEqual(observation.battery_discharge_w, 2000)
        self.assertIsNone(self.guard.tracker.evaluate(AT, "battery", observation))
        self.at += timedelta(seconds=90)
        self.receive("2026-10-02T16:54:19", 1200)
        self.assertEqual(self.guard.tracker.evaluate(self.at, "battery", self.guard._observation(self.at)), "battery")
        self.assertIsNone(self.guard.tracker.evaluate(self.at, "battery", self.guard._observation(self.at)))

    def test_newer_site_updates_are_usable_for_live_gauge(self):
        self.receive()
        self.at += timedelta(seconds=10)
        self.c.hass.states["sensor.battery"].last_updated = self.at
        sources = dashboard_attributes(self.c)["power_flow"]["charging_sources"]
        self.assertAlmostEqual(sources["battery_w"], 2000)

    def test_unchanged_zero_battery_does_not_hide_solar_or_enable_stop(self):
        battery = self.c.hass.states["sensor.battery"]
        battery.state = "0"
        battery.last_updated = AT - timedelta(hours=2)
        battery.last_reported = battery.last_updated
        self.c.hass.states["sensor.pv"].state = "10320"
        self.c.grid_power = -2146
        self.receive()
        sources = dashboard_attributes(self.c)["power_flow"]["charging_sources"]
        self.assertAlmostEqual(sources["solar_w"], 7000)
        self.assertAlmostEqual(sources["unknown_w"], 0)
        self.assertAlmostEqual(self.c.site_accounting.buckets["direct_solar"], .05)
        self.assertIsNone(self.guard._observation(AT).battery_discharge_w)
        self.assertIsNone(self.guard.tracker.evaluate(AT, "battery", self.guard._observation(AT)))

    def test_site_report_during_packet_transit_does_not_create_unknown_energy(self):
        self.at = AT + timedelta(seconds=2)
        for state in self.c.hass.states.values():
            state.last_updated = AT + timedelta(milliseconds=200)
        self.c.external_meter_last_updated_at = (AT + timedelta(seconds=1)).isoformat()
        self.receive()
        self.assertAlmostEqual(self.c.site_accounting.buckets["unknown"], 0)
        self.assertAlmostEqual(self.c.site_accounting.buckets["battery_unknown"], 2 * 30 / 3600)
        self.assertAlmostEqual(sum(self.c.site_accounting.buckets.values()), .05)

    def test_future_site_report_beyond_receipt_is_not_used_for_accounting(self):
        self.at = AT + timedelta(seconds=1)
        self.c.hass.states["sensor.pv"].last_updated = AT + timedelta(seconds=2)
        self.c.hass.states["sensor.battery"].state = "0"
        self.receive()
        self.assertAlmostEqual(self.c.site_accounting.buckets["unknown"], .05)

    def test_repeated_sensor_poll_offsets_keep_solar_and_total_energy_in_step(self):
        self.c.hass.states["sensor.battery"].state = "0"
        self.c.hass.states["sensor.pv"].state = "10390"
        self.c.grid_power = -1344
        self.c.site_accounting.last_meter_at = AT - timedelta(seconds=5)
        for index in range(9):
            sample_at = AT + timedelta(seconds=5 * index)
            self.at = sample_at + timedelta(seconds=1)
            if index % 3 == 0:
                self.c.hass.states["sensor.pv"].last_reported = sample_at + timedelta(milliseconds=200)
            self.receive(sample_at.isoformat(), 1010 + 10 * index)
        self.assertAlmostEqual(self.c.site_accounting.buckets["direct_solar"], .09)
        self.assertAlmostEqual(self.c.site_accounting.buckets["unknown"], 0)
        self.assertAlmostEqual(sum(self.c.site_accounting.buckets.values()), .09)

    def test_larger_source_offset_remains_unknown_despite_late_packet_receipt(self):
        self.at = AT + timedelta(seconds=20)
        self.c.hass.states["sensor.pv"].last_updated = AT + timedelta(seconds=10)
        self.c.hass.states["sensor.battery"].state = "0"
        self.receive()
        self.assertAlmostEqual(self.c.site_accounting.buckets["unknown"], .05)

    def test_unavailable_battery_cannot_be_assumed_zero_for_solar(self):
        self.c.hass.states["sensor.battery"].state = "unavailable"
        self.receive()
        sources = dashboard_attributes(self.c)["power_flow"]["charging_sources"]
        self.assertAlmostEqual(sources["solar_w"], 0)
        self.assertAlmostEqual(sources["unknown_w"], 7000)
        self.assertAlmostEqual(self.c.site_accounting.buckets["unknown"], .05)

    def test_stale_future_invalid_and_dst_ambiguous_samples_cannot_trigger_stop(self):
        for raw in ("2026-10-02T16:40:00", "2026-10-02T17:52:49", "bad",
                    "2026-10-25T02:30:00", "2026-03-29T02:30:00"):
            with self.subTest(raw=raw):
                self.receive(raw)
                self.assertNotIn("charging_sources", dashboard_attributes(self.c)["power_flow"])
                self.assertFalse(self.guard._observation(self.at).eligible)
        self.receive()
        self.c.last_meter_values["received_at"] = (AT - timedelta(hours=1)).isoformat()
        self.assertNotIn("charging_sources", dashboard_attributes(self.c)["power_flow"])
        self.assertFalse(self.guard._observation(AT).eligible)

    def test_future_timestamp_does_not_advance_accounting_checkpoint(self):
        previous_at = self.c.site_accounting.last_meter_at
        self.receive("2026-10-02T17:52:49")
        self.assertEqual(self.c.site_accounting.last_meter_at, previous_at)
        self.assertEqual(self.c.site_accounting.last_meter_wh, 1000)
        self.receive()
        self.assertAlmostEqual(sum(self.c.site_accounting.buckets.values()), .05)

    def test_energy_gap_is_unknown_instead_of_retroactively_classified(self):
        self.c.site_accounting.last_meter_at = AT - timedelta(hours=2)
        self.receive()
        self.assertAlmostEqual(self.c.site_accounting.buckets["unknown"], .05)
        self.assertEqual(self.c.site_accounting.buckets["battery_unknown"], 0)

    def test_restored_numeric_transaction_matches_live_meter_for_stop_guard(self):
        self.c.sessions = coordinator_module.SessionLifecycle(self.c)
        self.c.id_tag = None
        stored = self.c._active_session_state()
        self.c._restore_active_session_state(stored)
        self.assertEqual(self.c.transaction_id, 27)
        self.receive()
        self.assertTrue(self.guard._observation(AT).eligible)
        self.c.last_meter_values["transaction_id"] = 28
        self.assertFalse(self.guard._observation(AT).eligible)
