"""Binary sensors are on/off views of the charger snapshot."""

import unittest
from types import SimpleNamespace

from tests.support import build_coordinator, install_binary_sensor_stubs, load_package_module

install_binary_sensor_stubs()
platform = load_package_module("binary_sensor")
ENTRY = SimpleNamespace(entry_id="entry-test")


class BinarySensorTest(unittest.TestCase):
    def setUp(self):
        self.coordinator = build_coordinator()
        self.coordinator.last_update_success = True
        self.sensors = {
            description.key: platform.ThorBinarySensor(self.coordinator, ENTRY, description)
            for description in platform.BINARY_SENSOR_DESCRIPTIONS
        }

    def states(self, connected, status):
        self.coordinator.connected = connected
        self.coordinator.status = status
        return {
            key: (sensor.is_on if sensor.available else "unavailable")
            for key, sensor in self.sensors.items()
        }

    def test_identity_and_device_classes(self):
        self.assertEqual(
            {
                key: (sensor._attr_unique_id, sensor.entity_description.translation_key)
                for key, sensor in self.sensors.items()
            },
            {
                key: (f"entry-test_{key}", key)
                for key in ("vehicle_connected", "charging", "charger_fault", "charger_connected")
            },
        )
        self.assertEqual(
            [description.device_class for description in platform.BINARY_SENSOR_DESCRIPTIONS],
            ["PLUG", "BATTERY_CHARGING", "PROBLEM", "CONNECTIVITY"],
        )

    def test_states_follow_the_snapshot(self):
        cases = {
            (False, None): ("unavailable", "unavailable", "unavailable", False),
            # A retained status from before the disconnect says nothing live.
            (False, "Charging"): ("unavailable", "unavailable", "unavailable", False),
            (True, None): ("unavailable", "unavailable", "unavailable", True),
            (True, "Available"): (False, False, False, True),
            (True, "Preparing"): (True, False, False, True),
            (True, "Charging"): (True, True, False, True),
            (True, "SuspendedEV"): (True, False, False, True),
            (True, "SuspendedEVSE"): (True, False, False, True),
            (True, "Finishing"): (True, False, False, True),
            # These statuses do not say whether a car is plugged in.
            (True, "Faulted"): (None, False, True, True),
            (True, "Reserved"): (None, False, False, True),
            (True, "Unavailable"): (None, False, False, True),
        }
        for (connected, status), expected in cases.items():
            with self.subTest(connected=connected, status=status):
                self.assertEqual(
                    self.states(connected, status),
                    dict(
                        zip(
                            ("vehicle_connected", "charging", "charger_fault", "charger_connected"),
                            expected,
                            strict=True,
                        )
                    ),
                )

    def test_failed_coordinator_makes_every_sensor_unavailable(self):
        self.coordinator.last_update_success = False

        self.assertEqual(set(self.states(True, "Charging").values()), {"unavailable"})


if __name__ == "__main__":
    unittest.main()
