"""Charged-energy sensor value before and after the first sample.

The sensor is ``total_increasing``.  Reporting 0 while the coordinator has no
energy value yet (after a start-up or reload during a session) looks like a
meter reset, so the next sample of the running session would be counted twice
by long-term statistics and utility meters.  These tests load ``sensor.py``
with small Home Assistant stand-ins; no Home Assistant install is needed.
"""

import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace

PACKAGE_PATH = Path(__file__).parents[1] / "custom_components" / "growatt_thor"
PACKAGE_NAME = "thor_energy_sensor_target"


def _module(name):
    """Return a stand-in module, creating it and linking it to its parent."""
    module = sys.modules.get(name)
    if module is None:
        module = ModuleType(name)
        sys.modules[name] = module
    parent_name, _, child = name.rpartition(".")
    if parent_name:
        setattr(_module(parent_name), child, module)
    return module


def _default(module, name, value):
    if not hasattr(module, name):
        setattr(module, name, value)


class _NamedMembers(type):
    """Enum-like stand-in: every attribute is its own name."""

    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return name


class _Description:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _named(name):
    return _NamedMembers(name, (), {})


def _install_home_assistant_stand_ins():
    _module("homeassistant.helpers.entity_registry")
    sensor = _module("homeassistant.components.sensor")
    _default(sensor, "SensorEntity", type("SensorEntity", (), {}))
    _default(sensor, "SensorDeviceClass", _named("SensorDeviceClass"))
    _default(sensor, "SensorStateClass", _named("SensorStateClass"))
    _default(sensor, "SensorEntityDescription", _Description)
    _default(
        _module("homeassistant.helpers.update_coordinator"),
        "CoordinatorEntity",
        type("CoordinatorEntity", (), {}),
    )
    _default(
        _module("homeassistant.helpers.entity"),
        "EntityCategory",
        _named("EntityCategory"),
    )
    const = _module("homeassistant.const")
    for unit in (
        "UnitOfPower",
        "UnitOfEnergy",
        "UnitOfElectricCurrent",
        "UnitOfElectricPotential",
        "UnitOfTemperature",
        "UnitOfTime",
    ):
        _default(const, unit, _named(unit))


def _load_sensor_module():
    _install_home_assistant_stand_ins()
    package = sys.modules.get(PACKAGE_NAME)
    if package is None:
        # Register the package without running __init__.py, which needs the
        # full Home Assistant runtime; sensor.py only needs its siblings.
        package = ModuleType(PACKAGE_NAME)
        package.__path__ = [str(PACKAGE_PATH)]
        sys.modules[PACKAGE_NAME] = package
    name = f"{PACKAGE_NAME}.sensor"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PACKAGE_PATH / "sensor.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sensor = _load_sensor_module()


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
