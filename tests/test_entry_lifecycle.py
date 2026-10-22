"""Entry setup and unload with two chargers; install tests/requirements-auth.txt.

Runs the real async_setup_entry / async_unload_entry and the real OCPP server
on free local ports.  Only Home Assistant itself and the coordinator are
replaced by small stand-ins, so the tests check which port and runtime each
entry owns after a failure (review on PR #58).
"""
import asyncio
import importlib.util
from pathlib import Path
import socket
import sys
from types import ModuleType, SimpleNamespace
import unittest

HAS_DEPS = all(
    importlib.util.find_spec(name) is not None
    for name in ("ocpp", "websockets", "voluptuous")
)

PACKAGE_PATH = Path(__file__).parents[1] / "custom_components" / "growatt_thor"
PACKAGE_NAME = "thor_entry_lifecycle_target"


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


class _Platform:
    SENSOR = "sensor"
    NUMBER = "number"
    SWITCH = "switch"
    SELECT = "select"
    TIME = "time"
    BUTTON = "button"


class _HomeAssistantError(Exception):
    pass


class _ConfigEntryNotReady(_HomeAssistantError):
    pass


class _ServiceValidationError(_HomeAssistantError):
    pass


def _install_home_assistant_stand_ins():
    _default(_module("homeassistant.config_entries"), "ConfigEntry", object)
    core = _module("homeassistant.core")
    _default(core, "HomeAssistant", object)
    _default(core, "ServiceCall", object)
    _default(_module("homeassistant.const"), "Platform", _Platform)
    _default(
        _module("homeassistant.components.persistent_notification"),
        "async_create",
        lambda *args, **kwargs: None,
    )
    exceptions = _module("homeassistant.exceptions")
    _default(exceptions, "HomeAssistantError", _HomeAssistantError)
    _default(exceptions, "ConfigEntryNotReady", _ConfigEntryNotReady)
    _default(exceptions, "ServiceValidationError", _ServiceValidationError)
    _module("homeassistant.helpers.device_registry")
    _module("homeassistant.helpers.entity_registry")
    _default(_module("homeassistant.helpers.storage"), "Store", object)
    _default(_module("homeassistant.helpers.config_validation"), "string", str)
    _default(
        _module("homeassistant.helpers.update_coordinator"),
        "DataUpdateCoordinator",
        object,
    )


def _load_integration():
    _install_home_assistant_stand_ins()
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        PACKAGE_PATH / "__init__.py",
        submodule_search_locations=[str(PACKAGE_PATH)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)
    return module


if HAS_DEPS:
    integration = _load_integration()


STORES = {}


class _MemoryStore:
    def __init__(self, hass, version, key):
        self.key = key

    async def async_load(self):
        return STORES.get(self.key)

    async def async_save(self, data):
        STORES[self.key] = data


class _Coordinator:
    """Stand-in that records the lifecycle calls made by the integration."""

    instances = []

    def __init__(self, hass, source_instance_id=None, seed_from_legacy=True):
        self.hass = hass
        self.source_instance_id = source_instance_id
        self.runtime_data = {}
        self.charge_point_id = None
        self.connected = False
        self.location = ""
        self.shutdown_calls = 0
        _Coordinator.instances.append(self)

    async def async_load_storage(self):
        pass

    async def async_shutdown(self):
        self.shutdown_calls += 1

    def set_charge_point(self, cp_id):
        self.charge_point_id = cp_id

    def set_disconnected(self):
        self.connected = False


class _DeviceRegistry:
    def async_get_device_by_identifier(self, identifier, config_entry_id):
        return None


class _ConfigEntries:
    def __init__(self):
        self.entries = []
        self.fail_platform_setup = set()
        self.fail_platform_unload = set()

    def async_entries(self, domain):
        return list(self.entries)

    def async_update_entry(self, entry, **kwargs):
        if "data" in kwargs:
            entry.data = kwargs["data"]

    async def async_forward_entry_setups(self, entry, platforms):
        if entry.entry_id in self.fail_platform_setup:
            raise RuntimeError("platform setup failed")

    async def async_unload_platforms(self, entry, platforms):
        return entry.entry_id not in self.fail_platform_unload


class _Hass:
    def __init__(self, loop):
        self.loop = loop
        self.data = {}
        self.config_entries = _ConfigEntries()
        self.tasks = []

    def async_create_task(self, coroutine, name=None):
        task = asyncio.ensure_future(coroutine)
        self.tasks.append(task)
        return task

    def async_create_background_task(self, coroutine, name=None):
        return self.async_create_task(coroutine, name)

    async def async_add_executor_job(self, function, *args):
        return function(*args)


def _free_port():
    with socket.socket() as sock:
        sock.bind(("0.0.0.0", 0))
        return sock.getsockname()[1]


def _port_is_free(port):
    with socket.socket() as sock:
        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            return False
        return True


@unittest.skipUnless(HAS_DEPS, "Install tests/requirements-auth.txt for lifecycle tests")
class EntryLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        STORES.clear()
        _Coordinator.instances.clear()
        self.patches = {
            "GrowattCoordinator": integration.GrowattCoordinator,
            "Store": integration.Store,
            "dr": integration.dr,
        }
        integration.GrowattCoordinator = _Coordinator
        integration.Store = _MemoryStore
        integration.dr = SimpleNamespace(async_get=lambda hass: _DeviceRegistry())
        self.hass = _Hass(asyncio.get_running_loop())

    async def asyncTearDown(self):
        for entry_id, runtime in list(
            self.hass.data.get(integration.DOMAIN, {}).items()
        ):
            server = runtime.get("server")
            if server is not None:
                server.close()
                await server.wait_closed()
        for task in self.hass.tasks:
            task.cancel()
        for task in self.hass.tasks:
            try:
                await task
            except BaseException:
                pass
        for name, value in self.patches.items():
            setattr(integration, name, value)

    def entry(self, entry_id, port):
        entry = SimpleNamespace(
            entry_id=entry_id,
            title=entry_id,
            data={"port": port, "poll_interval": 30, "location": ""},
        )
        self.hass.config_entries.entries.append(entry)
        return entry

    def runtime(self, entry_id):
        return self.hass.data.get(integration.DOMAIN, {}).get(entry_id)

    async def test_failed_platform_setup_frees_its_port_and_keeps_the_other_charger(self):
        right = self.entry("entry-right", _free_port())
        left = self.entry("entry-left", _free_port())
        self.hass.config_entries.fail_platform_setup.add("entry-left")

        self.assertTrue(await integration.async_setup_entry(self.hass, right))
        with self.assertRaises(RuntimeError):
            await integration.async_setup_entry(self.hass, left)

        self.assertTrue(_port_is_free(left.data["port"]))
        self.assertIsNone(self.runtime("entry-left"))
        right_runtime = self.runtime("entry-right")
        self.assertIsNotNone(right_runtime)
        self.assertTrue(right_runtime["server"].is_serving())
        self.assertFalse(right_runtime["polling_task"].done())
        self.assertFalse(_port_is_free(right.data["port"]))

        # The failed entry can be set up again once its platforms work.
        self.hass.config_entries.fail_platform_setup.clear()
        self.assertTrue(await integration.async_setup_entry(self.hass, left))
        self.assertTrue(self.runtime("entry-left")["server"].is_serving())

    async def test_failed_platform_unload_keeps_the_entry_running(self):
        left = self.entry("entry-left", _free_port())
        self.assertTrue(await integration.async_setup_entry(self.hass, left))
        runtime = self.runtime("entry-left")
        coordinator = runtime["coordinator"]
        self.hass.config_entries.fail_platform_unload.add("entry-left")

        self.assertFalse(await integration.async_unload_entry(self.hass, left))

        self.assertIs(self.runtime("entry-left"), runtime)
        self.assertTrue(runtime["server"].is_serving())
        self.assertFalse(runtime["polling_task"].done())
        self.assertEqual(coordinator.shutdown_calls, 0)
        self.assertFalse(_port_is_free(left.data["port"]))

        # A later successful unload tears everything down.
        self.hass.config_entries.fail_platform_unload.clear()
        polling_task = runtime["polling_task"]
        server = runtime["server"]
        self.assertTrue(await integration.async_unload_entry(self.hass, left))
        self.assertIsNone(self.runtime("entry-left"))
        self.assertTrue(polling_task.done())
        self.assertFalse(server.is_serving())
        self.assertEqual(coordinator.shutdown_calls, 1)
        self.assertTrue(_port_is_free(left.data["port"]))

    async def test_unloading_one_entry_leaves_the_other_untouched(self):
        right = self.entry("entry-right", _free_port())
        left = self.entry("entry-left", _free_port())
        self.assertTrue(await integration.async_setup_entry(self.hass, right))
        self.assertTrue(await integration.async_setup_entry(self.hass, left))
        right_runtime = self.runtime("entry-right")

        self.assertTrue(await integration.async_unload_entry(self.hass, left))

        self.assertTrue(_port_is_free(left.data["port"]))
        self.assertIs(self.runtime("entry-right"), right_runtime)
        self.assertTrue(right_runtime["server"].is_serving())
        self.assertEqual(right_runtime["coordinator"].shutdown_calls, 0)


if __name__ == "__main__":
    unittest.main()
