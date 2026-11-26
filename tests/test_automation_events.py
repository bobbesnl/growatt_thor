"""Automation events fire once per observation with a stable, RFID-free payload."""

import json
import unittest
from types import SimpleNamespace

from tests.support import build_coordinator, load_package_module

events_module = load_package_module("runtime.automation_events")
results = load_package_module("runtime.write_results")
AT = "2026-11-04T10:00:00Z"


class AutomationEventsTest(unittest.TestCase):
    def setUp(self):
        self.c = c = build_coordinator()
        c.hass = SimpleNamespace(
            config=SimpleNamespace(time_zone="UTC"),
            data={},
            async_create_task=lambda coroutine: coroutine.close(),
        )
        c.now = lambda: AT
        c.async_set_updated_data = lambda _: None
        c.schedule_storage_save = lambda: None
        c.schedule_fault_storage_save = lambda: None
        self.fired = []
        c.events.connect(lambda event_type, data: self.fired.append((event_type, data)))

    def of_type(self, event_type):
        return [data for fired_type, data in self.fired if fired_type == event_type]

    def test_command_result_fires_the_public_result_once(self):
        result = results.ChargerCommandResult.from_write_result(
            command_id="abc",
            command_name="start_charging",
            queued_at=AT,
            completed_at=AT,
            result=results.ChargerWriteResult.failed("charger_rejected"),
        )

        self.c.publish_write_result(result)

        self.assertEqual(self.fired, [("growatt_thor_command_result", result.as_dict())])
        self.assertEqual(self.fired[0][1]["status"], "failed")

    def test_session_events_identify_the_session_without_the_rfid_tag(self):
        self.c.sessions.start_transaction(42, "PRIVATE-RFID", connector_id=1, meter_start=1000)
        # A stop for another transaction must not complete this one.
        self.c.sessions.stop_transaction(transaction_id=41, meter_stop=1200, reason="Remote")
        self.c.sessions.stop_transaction(
            transaction_id=42, meter_stop=3500, reason="EVDisconnected"
        )

        self.assertEqual(
            self.of_type("growatt_thor_session_started"),
            [
                {
                    "transaction_id": 42,
                    "connector_id": 1,
                    "meter_start_wh": 1000.0,
                    "started_at": AT,
                }
            ],
        )
        (completed,) = self.of_type("growatt_thor_session_completed")
        self.assertEqual(
            completed,
            {
                "transaction_id": 42,
                "reason": "EVDisconnected",
                "meter_start_wh": 1000.0,
                "meter_stop_wh": 3500.0,
                "energy_kwh": 2.5,
                "effective_charging_duration_minutes": completed[
                    "effective_charging_duration_minutes"
                ],
                "stopped_at": AT,
            },
        )
        self.assertNotIn("PRIVATE-RFID", json.dumps(self.fired))

    def test_energy_is_omitted_when_the_meter_readings_do_not_fit(self):
        for meter_start, meter_stop in ((None, 3500), (1000, None), (4000, 3500), (True, 2)):
            with self.subTest(meter_start=meter_start, meter_stop=meter_stop):
                self.fired.clear()
                self.c.sessions.start_transaction(7, None, connector_id=1, meter_start=meter_start)
                self.c.sessions.stop_transaction(transaction_id=7, meter_stop=meter_stop)
                (completed,) = self.of_type("growatt_thor_session_completed")
                self.assertIsNone(completed["energy_kwh"])

    def test_fault_fires_on_the_transition_into_faulted_only(self):
        ingest = self.c.ingest
        ingest.observe_status_notification(1, "Available", "NoError")
        ingest.observe_status_notification(1, "Faulted", "GroundFailure")
        ingest.observe_status_notification(1, "Faulted", "GroundFailure")
        ingest.observe_status_notification(1, "Available", "NoError")
        ingest.observe_status_notification(1, "Faulted", "OverCurrentFailure")

        faults = self.of_type("growatt_thor_fault")
        self.assertEqual(
            [fault["ocpp_error_code"] for fault in faults],
            ["GroundFailure", "OverCurrentFailure"],
        )
        self.assertEqual(
            set(faults[0]), {"category", "ocpp_error_code", "connector_id", "observed_at"}
        )
        self.assertEqual(faults[0]["category"], self.c.last_charger_fault.category)

    def test_target_state_changes_report_the_previous_state_of_the_same_request(self):
        events = self.c.events
        events.target_state_changed(None, {"request_id": "a", "state": "queued"})
        events.target_state_changed(
            {"request_id": "a", "state": "queued"}, {"request_id": "a", "state": "queued"}
        )
        events.target_state_changed(
            {"request_id": "a", "state": "queued"}, {"request_id": "a", "state": "active"}
        )
        events.target_state_changed(
            {"request_id": "a", "state": "active"}, {"request_id": "b", "state": "queued"}
        )
        events.target_state_changed({"request_id": "b", "state": "queued"}, None)
        events.target_state_changed(None, None)

        self.assertEqual(
            self.of_type("growatt_thor_target_state_changed"),
            [
                {"request_id": "a", "state": "queued", "previous_state": None},
                {"request_id": "a", "state": "active", "previous_state": "queued"},
                {"request_id": "b", "state": "queued", "previous_state": None},
                {"request_id": "b", "state": None, "previous_state": "queued"},
            ],
        )

    def test_publication_failures_stay_behind_the_event_boundary(self):
        def broken(event_type, data):
            raise RuntimeError("listener failed")

        self.c.events.connect(broken)
        with self.assertLogs(events_module.__name__, "ERROR"):
            self.c.sessions.start_transaction(42, None, connector_id=1, meter_start=0)

        self.assertEqual(self.c.transaction_id, 42)

    def test_unconnected_events_are_dropped(self):
        self.c.events.connect(None)
        self.c.sessions.start_transaction(42, None, connector_id=1, meter_start=0)

        self.assertEqual(self.fired, [])

    def test_every_device_trigger_names_a_declared_event(self):
        declared = {
            value
            for name, value in vars(events_module).items()
            if name.startswith("EVENT_") and isinstance(value, str)
        }
        self.assertEqual(set(events_module.DEVICE_TRIGGER_EVENTS.values()), declared)


if __name__ == "__main__":
    unittest.main()
