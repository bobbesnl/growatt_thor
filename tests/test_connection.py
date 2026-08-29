"""Tests for OCPP connection liveness tracking."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
    / "connection.py"
)
OCPP_SERVER_PATH = MODULE_PATH.with_name("ocpp_server.py")
SPEC = importlib.util.spec_from_file_location(
    "growatt_thor_connection_test_target",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
connection = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = connection
SPEC.loader.exec_module(connection)


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
