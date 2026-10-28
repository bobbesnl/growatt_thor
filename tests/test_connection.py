"""Tests for OCPP connection liveness tracking."""

from __future__ import annotations

import unittest

from support import PACKAGE_PATH, load_package_module

MODULE_PATH = PACKAGE_PATH / "ocpp/connection.py"
OCPP_SERVER_PATH = MODULE_PATH.with_name("server.py")
connection = load_package_module("growatt_thor_connection_test_target", MODULE_PATH)


class OcppConnectionActivityTest(unittest.TestCase):
    """Verify activity timeout behavior at its boundaries."""

    def test_default_timeout_allows_three_heartbeat_intervals(self):
        self.assertEqual(connection.OCPP_HEARTBEAT_INTERVAL_SECONDS, 60)
        self.assertEqual(connection.MISSED_ACTIVITY_LIMIT, 3)
        self.assertEqual(connection.CONNECTION_ACTIVITY_TIMEOUT_SECONDS, 180)

    def test_connection_becomes_stale_at_timeout(self):
        activity = connection.OcppConnectionActivity(100.0)

        self.assertFalse(activity.is_stale(279.999))
        self.assertTrue(activity.is_stale(280.0))

    def test_inbound_message_resets_timeout(self):
        activity = connection.OcppConnectionActivity(100.0)
        activity.mark(250.0)

        self.assertFalse(activity.is_stale(429.999))
        self.assertTrue(activity.is_stale(430.0))

    def test_idle_time_does_not_go_negative(self):
        activity = connection.OcppConnectionActivity(100.0)

        self.assertEqual(activity.idle_seconds(99.0), 0.0)

    def test_watchdog_does_not_block_home_assistant_startup(self):
        source = OCPP_SERVER_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "watchdog_task = hass.async_create_background_task(",
            source,
        )
        self.assertNotIn(
            "watchdog_task = hass.async_create_task(",
            source,
        )


if __name__ == "__main__":
    unittest.main()
