"""Legacy module paths retain the same domain objects after file moves."""

import importlib
import sys
import unittest
from pathlib import Path
from types import ModuleType

from support import install_ha_stubs

install_ha_stubs()

PACKAGE = "thor_module_compatibility_test"
package = ModuleType(PACKAGE)
package.__path__ = [str(Path(__file__).parents[1] / "custom_components/growatt_thor")]
sys.modules[PACKAGE] = package


class ModuleCompatibilityTest(unittest.TestCase):
    def test_old_imports_resolve_to_the_canonical_objects(self):
        cases = (
            ("runtime.write_queue", "runtime.write_results", "ChargerWriteResult"),
            ("runtime.time", "timestamps", "utc_instant"),
            ("sessions.time", "sessions.display_times", "session_time_zone"),
            ("energy.accounting", "energy.allocation", "AccountingPolicy"),
            ("energy.session_accounting", "energy.session_accumulator", "SessionAccumulator"),
            ("energy.accounting_runtime", "energy.site_inputs", "site_inputs"),
            ("energy.observations", "energy.site_observations", "read_site_observations"),
            ("energy.stop_guard", "energy.stop_guard_policy", "StopGuardTracker"),
            ("energy.stop_runtime", "energy.stop_guard", "EnergyStopGuard"),
            ("charging.controls", "charging.control_capabilities", "ChargingControl"),
            (
                "charging.session_controls",
                "charging.start_stop_rules",
                "start_revalidation_failure",
            ),
            ("runtime.write_queue", "runtime.write_results", "_stringify"),
        )
        for old, current, name in cases:
            with self.subTest(old=old, name=name):
                legacy = importlib.import_module(f"{PACKAGE}.{old}")
                canonical = importlib.import_module(f"{PACKAGE}.{current}")
                self.assertIs(getattr(legacy, name), getattr(canonical, name))
