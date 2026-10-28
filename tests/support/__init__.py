"""Shared minimal Home Assistant stand-ins for focused module tests."""

import asyncio
import sys
from importlib import import_module, util
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import SkipTest
from unittest.mock import patch


class HomeAssistantError(Exception):
    def __init__(
        self, *args, translation_domain=None, translation_key=None, translation_placeholders=None
    ):
        super().__init__(*args or (translation_key,))
        self.translation_domain = translation_domain
        self.translation_key = translation_key
        self.translation_placeholders = translation_placeholders


class ServiceValidationError(HomeAssistantError):
    pass


def install_ha_stubs():
    """Provide action exceptions without replacing an existing HA implementation."""
    root = sys.modules.setdefault("homeassistant", ModuleType("homeassistant"))
    exceptions = sys.modules.setdefault(
        "homeassistant.exceptions", ModuleType("homeassistant.exceptions")
    )
    root.exceptions = exceptions
    if not hasattr(exceptions, "HomeAssistantError"):
        exceptions.HomeAssistantError = HomeAssistantError
    if not hasattr(exceptions, "ServiceValidationError"):
        exceptions.ServiceValidationError = ServiceValidationError


# Focused modules are loaded without executing the HA integration initializer.
# Preserve explicit per-test namespaces where tests patch module globals.

PACKAGE_PATH = Path(__file__).resolve().parents[2] / "custom_components/growatt_thor"


def register_package(name):
    """Register a test package without starting integration setup or services."""
    parent, _, child = name.rpartition(".")
    if parent:
        parent_module = sys.modules.setdefault(parent, ModuleType(parent))
        if not hasattr(parent_module, "__path__"):
            parent_module.__path__ = []
    package = sys.modules.setdefault(name, ModuleType(name))
    package.__path__ = [str(PACKAGE_PATH)]
    if parent:
        setattr(parent_module, child, package)
    return package


def load_package_module(name, filename=None, *, package_name="custom_components.growatt_thor"):
    """Load a focused module, retaining normal dependency and class identities."""
    if filename is not None:
        path = Path(filename)
        if path.is_absolute():
            path = path.relative_to(PACKAGE_PATH)
        module = path.with_suffix("").as_posix().replace("/", ".")
        suffix = "." + module
        package_name = name[: -len(suffix)] if name.endswith(suffix) else name
        name = module
    register_package(package_name)
    try:
        if name == "__init__":
            spec = util.spec_from_file_location(
                package_name,
                PACKAGE_PATH / "__init__.py",
                submodule_search_locations=[str(PACKAGE_PATH)],
            )
            value = util.module_from_spec(spec)
            sys.modules[package_name] = value
            spec.loader.exec_module(value)
            return value
        return import_module(f"{package_name}.{name}")
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] in {"ocpp", "websockets", "voluptuous"}:
            raise SkipTest("Install tests/requirements-auth.txt for protocol tests") from exc
        raise


class MemoryStore:
    """Checkpoint stand-in that records reads and saved snapshots."""

    def __init__(self, data=None):
        self.data = data
        self.loads = 0
        self.saved = []
        self.delays = []

    def async_delay_save(self, callback, delay):
        self.delays.append((callback, delay))

    async def async_load(self):
        self.loads += 1
        return self.data

    async def async_save(self, data):
        self.saved.append(data)
        self.data = data


class FakeHass(SimpleNamespace):
    """Small HA owner with deterministic task ownership for focused tests."""

    def __init__(self, loop=None, **kwargs):
        values = {"loop": loop, "data": {"growatt_thor": {}}, "config": None}
        values.update(kwargs)
        super().__init__(**values)

    def async_create_task(self, coroutine):
        return asyncio.create_task(coroutine)


def build_coordinator(store=None, legacy_store=None, entry_id="entry_test"):
    install_coordinator_stubs()
    coordinator_module = load_package_module("coordinator")

    def init_base(self, hass, *args, **kwargs):
        self.hass = hass

    with (
        patch.object(coordinator_module.DataUpdateCoordinator, "__init__", init_base),
        patch.object(coordinator_module, "Store", lambda *args: MemoryStore()),
    ):
        coordinator = coordinator_module.GrowattCoordinator(FakeHass(), entry_id)
    coordinator.updates = 0

    def _updated(_data):
        coordinator.updates += 1

    coordinator.async_set_updated_data = _updated
    coordinator.runtime_data = {}
    coordinator.source_instance_id = entry_id
    coordinator.connected = True
    coordinator._connection_changed.clear()
    coordinator.charge_point_id = "XGJ0000000000001"
    coordinator.status = None
    coordinator.power = None
    coordinator.phase_power = {}
    coordinator.currents = {}
    coordinator.voltages = {}
    coordinator.energy = None
    coordinator.temperature = None
    coordinator.transaction_id = None
    coordinator.last_meter_values = None
    coordinator.configuration_values = {}
    coordinator._store = store or MemoryStore()
    coordinator._legacy_store = legacy_store
    coordinator._transaction_id_allocator = coordinator_module.TransactionIdAllocator()
    coordinator.total_energy_charged = 0.0
    coordinator.last_charger_fault = None
    coordinator.effective_charging = coordinator_module.EffectiveChargingTracker()
    coordinator._pending_effective_charging_minutes = {}
    coordinator._restore_last_session_state(coordinator_module.LastSessionState.from_dict(None))
    return coordinator


def module(name):
    """Create an HA stand-in module and link it to its parent once."""
    value = sys.modules.setdefault(name, ModuleType(name))
    parent, _, child = name.rpartition(".")
    if parent:
        setattr(module(parent), child, value)
    return value


def default(target, name, value):
    if not hasattr(target, name):
        setattr(target, name, value)


class DataUpdateCoordinator:
    def __init__(self, hass, *args, **kwargs):
        self.hass = hass


def install_coordinator_stubs():
    install_ha_stubs()
    register_package("custom_components.growatt_thor")
    default(
        module("homeassistant.helpers.update_coordinator"),
        "DataUpdateCoordinator",
        DataUpdateCoordinator,
    )
    default(module("homeassistant.helpers.storage"), "Store", MemoryStore)


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


def install_sensor_stubs():
    module("homeassistant.helpers.entity_registry")
    sensor = module("homeassistant.components.sensor")
    default(sensor, "SensorEntity", type("SensorEntity", (), {}))
    default(sensor, "SensorDeviceClass", _named("SensorDeviceClass"))
    default(sensor, "SensorStateClass", _named("SensorStateClass"))
    default(sensor, "SensorEntityDescription", _Description)
    default(
        module("homeassistant.helpers.update_coordinator"),
        "CoordinatorEntity",
        type("CoordinatorEntity", (), {}),
    )
    default(
        module("homeassistant.helpers.entity"),
        "EntityCategory",
        _named("EntityCategory"),
    )
    const = module("homeassistant.const")
    for unit in (
        "UnitOfPower",
        "UnitOfEnergy",
        "UnitOfElectricCurrent",
        "UnitOfElectricPotential",
        "UnitOfTemperature",
        "UnitOfTime",
    ):
        default(const, unit, _named(unit))


def load_sensor_module():
    """Load the actual sensor platform with the shared minimal HA types."""
    install_sensor_stubs()
    return load_package_module("sensor", package_name="thor_energy_sensor_target")


def build_queue_coordinator(loop):
    coordinator = build_coordinator()
    coordinator.hass = FakeHass(loop)
    # Preserve queue-test timing while exercising complete lifecycle state.
    coordinator._connection_changed.set()
    coordinator.write_queue.min_write_interval = 0.0
    coordinator.write_queue.poll_pause_after_write = 0.0
    coordinator.async_set_updated_data = lambda data: None
    return coordinator
