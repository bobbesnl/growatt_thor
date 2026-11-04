"""Expected charger reboot after RebootRequired: writes and Start wait for the reconnect."""

import unittest

from tests.support import build_coordinator, load_package_module

reboot = load_package_module("runtime.charger_reboot")
controls = load_package_module("charging.control_capabilities")
commands = load_package_module("charging.commands")
card_data = load_package_module("presentation.card_data")


class FakeTimer:
    def __init__(self, delay, callback):
        self.delay = delay
        self.callback = callback
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class FakeLoop:
    def __init__(self):
        self.now = 1000.0
        self.timers = []

    def time(self):
        return self.now

    def call_later(self, delay, callback):
        timer = FakeTimer(delay, callback)
        self.timers.append(timer)
        return timer


class RebootWindowTest(unittest.TestCase):
    def test_window_is_pending_until_its_deadline_or_cleared(self):
        window = reboot.ChargerRebootWindow()
        self.assertFalse(window.is_open)
        self.assertFalse(window.pending(0))

        window.expect(10)
        self.assertTrue(window.pending(10 + reboot.REBOOT_WINDOW_SECONDS - 0.1))
        self.assertFalse(window.pending(10 + reboot.REBOOT_WINDOW_SECONDS))
        # A second RebootRequired restarts the window.
        window.expect(50)
        self.assertTrue(window.pending(10 + reboot.REBOOT_WINDOW_SECONDS))

        self.assertTrue(window.clear())
        self.assertFalse(window.clear())
        self.assertFalse(window.pending(50))

    def test_shared_guard_reports_the_reboot_after_a_lost_connection(self):
        def reason(**overrides):
            values = {"connected": True, "charger_faulted": False, "reboot_pending": False}
            return controls.charger_write_block_reason(**(values | overrides))

        self.assertIsNone(reason())
        self.assertEqual(reason(reboot_pending=True), "charger_rebooting")
        self.assertEqual(reason(reboot_pending=True, charger_faulted=True), "charger_rebooting")
        self.assertEqual(reason(reboot_pending=True, connected=False), "charger_disconnected")


class CoordinatorRebootTest(unittest.TestCase):
    def setUp(self):
        self.coordinator = build_coordinator()
        self.loop = FakeLoop()
        self.coordinator.hass.loop = self.loop

    def expect_reboot(self):
        self.coordinator.observe_reboot_required()
        return self.loop.timers[-1]

    def test_reboot_refuses_configuration_writes_and_start_but_not_stop(self):
        self.assertFalse(self.coordinator.charger_reboot_pending)
        updates = self.coordinator.updates

        self.expect_reboot()

        self.assertTrue(self.coordinator.charger_reboot_pending)
        self.assertGreater(self.coordinator.updates, updates)
        self.assertEqual(
            self.coordinator.write_block_reason(controls.ChargingControl.AUTHORIZATION_MODE),
            "charger_rebooting",
        )
        self.assertEqual(
            commands.StartChargingCommand(self.coordinator).write_block_reason,
            "charger_rebooting",
        )
        self.assertTrue(card_data.dashboard_attributes(self.coordinator)["charger_rebooting"])
        # Stop has no shared write guard; the reboot window must not add one.
        self.assertNotIn("write_block_reason", vars(commands.StopChargingCommand))

    def test_reconnect_ends_the_window_and_cancels_its_expiry(self):
        timer = self.expect_reboot()

        self.coordinator.observe_connected("XGJ0000000000001")

        self.assertFalse(self.coordinator.charger_reboot_pending)
        self.assertTrue(timer.cancelled)
        self.assertIsNone(
            self.coordinator.write_block_reason(controls.ChargingControl.AUTHORIZATION_MODE)
        )
        self.assertFalse(card_data.dashboard_attributes(self.coordinator)["charger_rebooting"])

    def test_missing_reboot_releases_writes_after_the_window(self):
        timer = self.expect_reboot()
        self.assertEqual(timer.delay, reboot.REBOOT_WINDOW_SECONDS)
        updates = self.coordinator.updates

        self.loop.now += reboot.REBOOT_WINDOW_SECONDS
        self.assertFalse(self.coordinator.charger_reboot_pending)
        with self.assertLogs(level="WARNING"):
            timer.callback()

        self.assertFalse(self.coordinator.reboot_window.is_open)
        self.assertGreater(self.coordinator.updates, updates)

    def test_second_reboot_restarts_the_expiry(self):
        first = self.expect_reboot()
        second = self.expect_reboot()

        self.assertTrue(first.cancelled)
        self.assertFalse(second.cancelled)


if __name__ == "__main__":
    unittest.main()
