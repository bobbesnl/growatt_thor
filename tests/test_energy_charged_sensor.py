"""Charged-energy sensor value before and after the first sample.

The sensor is ``total_increasing``.  Reporting 0 while the coordinator has no
energy value yet (after a start-up or reload during a session) looks like a
meter reset, so the next sample of the running session would be counted twice
by long-term statistics and utility meters.  These tests load ``sensor.py``
with small Home Assistant stand-ins; no Home Assistant install is needed.
"""

import unittest
from types import SimpleNamespace

from tests.support import load_sensor_module

PACKAGE_NAME = "thor_energy_sensor_target"


sensor = load_sensor_module()


def _sensor_for(energy_wh):
    # Skip the entity constructor: only the coordinator is read by the value.
    entity = object.__new__(sensor.EnergyChargedSensor)
    entity.coordinator = SimpleNamespace(energy=energy_wh)
    return entity


class EnergyChargedSensorTest(unittest.TestCase):
    def test_unknown_until_the_charger_reports_energy(self):
        self.assertIsNone(_sensor_for(None).native_value)

    def test_reports_kilowatt_hours_once_a_sample_arrived(self):
        self.assertEqual(_sensor_for(8218.0).native_value, 8.218)

    def test_new_transaction_still_starts_at_zero(self):
        # start_transaction() sets the energy to 0, which is a real reset.
        self.assertEqual(_sensor_for(0).native_value, 0)

    def test_sensor_is_total_increasing(self):
        self.assertEqual(
            sensor.EnergyChargedSensor._attr_state_class,
            sensor.SensorStateClass.TOTAL_INCREASING,
        )


if __name__ == "__main__":
    unittest.main()
