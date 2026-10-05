"""Tests for the session event contract and power-transition tracker."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest


COMPONENT = Path(__file__).parents[1] / "custom_components" / "growatt_thor"
PACKAGE_NAME = "thor_session_events_test"
PACKAGE = types.ModuleType(PACKAGE_NAME)
PACKAGE.__path__ = [str(COMPONENT)]
sys.modules[PACKAGE_NAME] = PACKAGE
SPEC = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.sessions.events", COMPONENT / "sessions/events.py"
)
session_events = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = session_events
SPEC.loader.exec_module(session_events)


class SessionEventTrackerTest(unittest.TestCase):
    def test_start_pause_resume_and_effective_stop_remain_distinct(self):
        tracker = session_events.SessionEventTracker.start(
            "2026-09-17T10:00:00Z",
            plugged_event=session_events.session_event(
                "plugged_in",
                "2026-09-17T09:59:30Z",
                "ocpp",
                "derived",
            ),
        )

        tracker.observe_power("2026-09-17T10:01:00Z", 7200)
        tracker.observe_power("2026-09-17T10:05:00Z", 0)
        tracker.observe_power("2026-09-17T10:08:00Z", 7100)
        tracker.observe_power("2026-09-17T10:15:00Z", 0)
        tracker.stop("2026-09-17T10:20:00Z", reason="EVDisconnected")

        self.assertEqual(
            [event["type"] for event in tracker.events],
            [
                "plugged_in",
                "transaction_started",
                "energy_flow_started",
                "charging_paused",
                "energy_flow_started",
                "energy_flow_stopped",
                "transaction_stopped",
            ],
        )
        self.assertEqual(tracker.events[3]["certainty"], "derived")
        self.assertEqual(tracker.events[5]["at"], "2026-09-17T10:15:00Z")
        self.assertEqual(tracker.events[-1]["reason"], "EVDisconnected")

    def test_reported_pause_without_final_meter_sample_and_resume(self):
        tracker = session_events.SessionEventTracker.start("2026-10-02T13:00:00Z")
        tracker.observe_power("2026-10-02T13:01:00Z", 7200)
        self.assertTrue(tracker.observe_suspension("2026-10-02T14:00:00Z", "suspended_ev"))
        pause = dict(tracker.events[-1])
        self.assertEqual(pause, {
            "type": "charging_paused", "at": "2026-10-02T14:00:00Z",
            "source": "ocpp", "certainty": "observed", "reason": "suspended_ev",
        })
        self.assertFalse(tracker.observe_suspension("2026-10-02T14:01:00Z", "suspended_ev"))
        self.assertFalse(tracker.observe_power("2026-10-02T13:59:00Z", 7200))
        self.assertFalse(tracker.observe_power("2026-10-02T14:02:00Z", 0))
        self.assertEqual(tracker.events[-1], pause)
        self.assertTrue(tracker.observe_power("2026-10-02T14:03:00Z", 7200))
        self.assertEqual(tracker.events[-1]["type"], "energy_flow_started")
        self.assertTrue(tracker.observe_suspension("2026-10-02T14:04:00Z", "suspended_ev"))

    def test_reported_pause_confirms_tentative_pause_and_handles_changed_reason(self):
        tracker = session_events.SessionEventTracker.start("2026-10-02T13:00:00Z")
        tracker.observe_power("2026-10-02T13:01:00Z", 7200)
        tracker.observe_power("2026-10-02T14:00:00Z", 0)
        self.assertTrue(tracker.observe_suspension("2026-10-02T14:00:01Z", "suspended_evse"))
        self.assertEqual(len(tracker.events), 3)
        self.assertEqual(tracker.events[-1]["certainty"], "observed")
        self.assertTrue(tracker.observe_suspension("2026-10-02T14:01:00Z", "suspended_ev"))
        self.assertFalse(tracker.observe_suspension("2026-10-02T14:02:00Z", "charging"))
        # Restoration retains deduplication without an extra persisted status flag.
        restored = session_events.SessionEventTracker(events=list(tracker.events), energy_flowing=False)
        self.assertFalse(restored.observe_suspension("2026-10-02T14:03:00Z", "suspended_ev"))
        restored.stop("2026-10-02T15:00:00Z", reason="EVDisconnected")
        self.assertEqual(restored.events[-1]["type"], "transaction_stopped")
        self.assertEqual(restored.events[2]["type"], "charging_paused")
        self.assertEqual(restored.events[-2]["type"], "energy_flow_stopped")
        self.assertEqual(restored.events[-2]["at"], "2026-10-02T14:01:00Z")

    def test_stop_request_is_recorded_once_and_only_when_called(self):
        tracker = session_events.SessionEventTracker.start(
            "2026-09-17T10:00:00Z"
        )

        self.assertTrue(tracker.record_stop_requested("2026-09-17T10:10:00Z"))
        self.assertFalse(tracker.record_stop_requested("2026-09-17T10:11:00Z"))

        requested = [
            event
            for event in tracker.events
            if event["type"] == "stop_requested"
        ]
        self.assertEqual(len(requested), 1)
        self.assertEqual(requested[0]["source"], "home_assistant")

    def test_protection_reason_survives_session_event_normalization(self):
        tracker = session_events.SessionEventTracker.start("2026-10-05T14:00:00Z")
        tracker.record_stop_requested("2026-10-05T14:08:56Z", reason="energy_guard_battery")
        tracker.stop("2026-10-05T14:09:01Z", reason="Remote")
        events = session_events.normalize_session_events(tracker.events)
        self.assertEqual(next(event['reason'] for event in events if event['type'] == 'stop_requested'), 'energy_guard_battery')

    def test_zero_power_only_session_does_not_invent_energy_flow_stop(self):
        tracker = session_events.SessionEventTracker.start(
            "2026-09-17T10:00:00Z"
        )
        tracker.observe_power("2026-09-17T10:01:00Z", 0)

        tracker.stop("2026-09-17T10:02:00Z", reason="EVDisconnected")

        self.assertNotIn(
            "energy_flow_stopped",
            {event["type"] for event in tracker.events},
        )
        self.assertEqual(tracker.events[-1]["type"], "transaction_stopped")

    def test_growatt_record_only_adds_explicit_missing_events(self):
        events = session_events.merge_growatt_record_events(
            [
                session_events.session_event(
                    "energy_flow_started",
                    "2026-09-17T10:01:00Z",
                    "meter",
                    "derived",
                )
            ],
            plug_time="2026-09-17 09:59:30",
            start_time="2026-09-17 10:00:00",
            end_time="2026-09-17 10:30:00",
            unplug_time=None,
        )

        self.assertEqual(
            [event["type"] for event in events],
            ["energy_flow_started", "plugged_in", "energy_flow_stopped"],
        )
        self.assertNotIn("unplugged", {event["type"] for event in events})

    def test_invalid_or_oversized_event_payload_is_filtered_and_bounded(self):
        payload = [
            {
                "type": "transaction_started",
                "at": "2026-09-17T09:59:00Z",
                "source": "ocpp",
                "certainty": "observed",
            },
            *[
            {
                "type": "energy_flow_started",
                "at": f"2026-09-17T10:{index:02d}:00Z",
                "source": "meter",
                "certainty": "derived",
            }
            for index in range(90)
            ],
        ]
        payload.append(
            {
                "type": "unknown",
                "at": "2026-09-17T12:00:00Z",
                "source": "meter",
                "certainty": "derived",
            }
        )

        normalized = session_events.normalize_session_events(payload)

        self.assertEqual(len(normalized), session_events.MAX_SESSION_EVENTS)
        self.assertEqual(normalized[0]["type"], "transaction_started")
        self.assertTrue(
            all(
                event["type"] in session_events.EVENT_TYPES
                for event in normalized
            )
        )


if __name__ == "__main__":
    unittest.main()
