"""Active-session checkpoint persistence through the real coordinator."""

from __future__ import annotations

import unittest

from tests.support import (
    build_coordinator,
    load_package_module,
)

coordinator_module = load_package_module("coordinator")


class _DelayedStore:
    def __init__(self):
        self.delays = []

    def async_delay_save(self, callback, delay):
        self.delays.append((callback, delay))


class ActiveSessionPersistenceTest(unittest.TestCase):
    """Verify the coordinator keeps an active history row across reloads."""

    def test_active_session_round_trip_restores_curve_and_events(self):
        source = build_coordinator()
        source.sessions = coordinator_module.SessionLifecycle(source)
        source.transaction_id = 27
        source.id_tag = "RFID-LIVE"
        source.energy = 2450
        source.active_transaction = {
            "start": {
                "received_at": "2026-09-21T08:00:00Z",
                "request": {
                    "timestamp": "2026-09-21T08:00:00Z",
                    "connector_id": 1,
                    "id_tag": "RFID-LIVE",
                    "meter_start": 100,
                },
                "response": {"transaction_id": 27},
            }
        }
        source._active_power_curve = [
            ["2026-09-21T08:01:00Z", 7100],
            ["2026-09-21T08:02:00Z", 0],
        ]
        source._session_event_tracker = coordinator_module.SessionEventTracker.start(
            "2026-09-21T08:00:00Z"
        )
        source._session_event_tracker.observe_power("2026-09-21T08:01:00Z", 7100)

        stored = source._active_session_state()
        restored = build_coordinator()
        restored.sessions = coordinator_module.SessionLifecycle(restored)
        restored._restore_active_session_state(stored)

        self.assertEqual(restored.transaction_id, 27)
        self.assertEqual(restored.id_tag, "RFID-LIVE")
        self.assertEqual(restored.energy, 2450)
        self.assertEqual(restored._active_power_curve, source._active_power_curve)
        self.assertEqual(
            restored._session_event_tracker.events,
            source._session_event_tracker.events,
        )
        self.assertTrue(restored._restored_active_session)

    def test_available_discards_row_but_keeps_details_for_record_correlation(self):
        coordinator = build_coordinator()
        coordinator.sessions = coordinator_module.SessionLifecycle(coordinator)
        coordinator._restored_active_session = True
        coordinator.transaction_id = "27"
        coordinator.id_tag = "RFID-LIVE"
        coordinator.energy = 2450
        coordinator.active_transaction = {"start": {"response": {"transaction_id": 27}}}
        coordinator._active_power_curve = [["2026-09-21T08:01:00Z", 7100]]
        coordinator._session_event_tracker = coordinator_module.SessionEventTracker.start(
            "2026-09-21T08:00:00Z"
        )
        coordinator.effective_charging = coordinator_module.EffectiveChargingTracker(
            transaction_id="27",
            elapsed_seconds=120,
            interval_count=2,
        )
        coordinator._pending_effective_charging_minutes = {}
        coordinator._store = _DelayedStore()

        coordinator._discard_unconfirmed_restored_session()

        self.assertIsNone(coordinator.active_transaction)
        self.assertIsNone(coordinator.transaction_id)
        self.assertEqual(
            coordinator.last_completed_transaction["power_curve"],
            [["2026-09-21T08:01:00Z", 7100]],
        )
        self.assertEqual(coordinator._pending_effective_charging_minutes["27"], 2.0)
        self.assertEqual(len(coordinator._store.delays), 1)
