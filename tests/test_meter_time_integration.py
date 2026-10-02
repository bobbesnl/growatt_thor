"""Exercise real THOR wall-clock samples through all live energy consumers."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

from test_write_queue import coordinator_module

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
        c.configuration_values = {}
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
            "site_grid_source": "thor_external", "site_solar_power_entity": "sensor.pv", "site_fixed_price": .3,
        }
        c.site_accounting = coordinator_module.SessionAccumulator(
            transaction_id="27", last_meter_wh=1000, last_meter_at=AT - timedelta(seconds=30),
        )

    def receive(self, timestamp="2026-10-02T16:52:49", energy=1050):
        self.c.process_meter_values([{"timestamp": timestamp, "sampledValue": [
            {"value": "7000", "measurand": "Power.Active.Import", "unit": "W"},
            {"value": str(energy), "measurand": "Energy.Active.Import.Register", "unit": "Wh"},
        ]}], transaction_id=27)

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

    def test_local_sample_reaches_accounting_and_curve(self):
        self.receive()
        packet = self.c.last_meter_values["meter_values"][0]
        self.assertEqual(packet["timestamp"], "2026-10-02T14:52:49Z")
        self.assertEqual(packet["raw"]["timestamp"], "2026-10-02T16:52:49")
        self.assertGreater(self.c.site_accounting.buckets["battery_unknown"], 0)
        self.assertAlmostEqual(sum(self.c.site_accounting.buckets.values()), .05)
        self.assertEqual(self.c._active_power_curve[-1][0], "2026-10-02T14:52:49Z")

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

