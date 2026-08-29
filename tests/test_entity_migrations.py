"""Tests for one-time Home Assistant entity-registry migrations."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest


COMPONENT_PATH = (
    Path(__file__).parents[1] / "custom_components" / "growatt_thor"
)
INIT_PATH = COMPONENT_PATH / "__init__.py"
PACKAGE_NAME = "growatt_thor_entity_migrations_test_package"
PACKAGE = types.ModuleType(PACKAGE_NAME)
PACKAGE.__path__ = [str(COMPONENT_PATH)]
sys.modules[PACKAGE_NAME] = PACKAGE


def _load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, COMPONENT_PATH / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_load_module(f"{PACKAGE_NAME}.const", "const.py")
entity_migrations = _load_module(
    f"{PACKAGE_NAME}.entity_migrations",
    "entity_migrations.py",
)


class _Entity:
    def __init__(
        self,
        unit_of_measurement,
        *,
        unique_id="entry-id_last_session_duration",
        entity_id="sensor.growatt_thor_ev_charger_last_session_duration",
        disabled_by=None,
    ):
        self.entity_id = entity_id
        self.config_entry_id = "entry-id"
        self.platform = "growatt_thor"
        self.unique_id = unique_id
        self.unit_of_measurement = unit_of_measurement
        self.disabled_by = disabled_by
        self.options = {
            "conversation": {"should_expose": False},
            "sensor": {"suggested_display_precision": 1},
            "sensor.private": {
                "suggested_unit_of_measurement": unit_of_measurement
            },
        }


class _Registry:
    def __init__(self, unit_of_measurement="min", *, exists=True):
        self.entity = _Entity(unit_of_measurement) if exists else None
        self.entities = (
            {self.entity.entity_id: self.entity}
            if self.entity is not None
            else {}
        )
        self.updates = []

    def async_get_entity_id(self, domain, platform, unique_id):
        if self.entity is None:
            return None
        if (
            domain == "sensor"
            and platform == self.entity.platform
            and unique_id == self.entity.unique_id
        ):
            return self.entity.entity_id
        return None

    def async_get(self, entity_id):
        if self.entity is not None and entity_id == self.entity.entity_id:
            return self.entity
        return None

    def async_update_entity(self, entity_id, **changes):
        self.updates.append((entity_id, changes))

    def async_update_entity_options(self, entity_id, domain, options):
        self.updates.append(
            (entity_id, {"domain": domain, "options": options})
        )


class _ExternalMeterRegistry:
    def __init__(self):
        self.entities = {}
        self.updates = []

    def add(self, suffix, *, disabled_by=None):
        entity = _Entity(
            None,
            unique_id=f"entry-id_{suffix}",
            entity_id=f"sensor.{suffix}",
            disabled_by=disabled_by,
        )
        self.entities[entity.entity_id] = entity
        return entity

    def async_get_entity_id(self, domain, platform, unique_id):
        return next(
            (
                entity.entity_id
                for entity in self.entities.values()
                if domain == "sensor"
                and platform == entity.platform
                and unique_id == entity.unique_id
            ),
            None,
        )

    def async_get(self, entity_id):
        return self.entities.get(entity_id)

    def async_update_entity(self, entity_id, **changes):
        self.updates.append((entity_id, changes))


class EntityMigrationTest(unittest.TestCase):
    def test_legacy_minute_override_is_migrated_to_hours(self):
        registry = _Registry()

        changed = entity_migrations.migrate_session_duration_unit(
            registry,
            "entry-id",
        )

        self.assertTrue(changed)
        self.assertEqual(
            registry.updates,
            [
                (
                    registry.entity.entity_id,
                    {
                        "domain": "sensor.private",
                        "options": {"suggested_unit_of_measurement": "h"},
                    },
                ),
                (
                    registry.entity.entity_id,
                    {
                        "domain": "sensor",
                        "options": {"suggested_display_precision": 2},
                    },
                ),
                (
                    registry.entity.entity_id,
                    {"unit_of_measurement": "h"},
                ),
            ],
        )

    def test_private_legacy_unit_is_migrated_when_public_unit_is_hours(self):
        registry = _Registry("h")
        registry.entity.options["sensor.private"][
            "suggested_unit_of_measurement"
        ] = "min"

        self.assertTrue(
            entity_migrations.migrate_session_duration_unit(
                registry,
                "entry-id",
            )
        )
        self.assertEqual(registry.updates[0][1]["domain"], "sensor.private")
        self.assertEqual(
            registry.updates[0][1]["options"],
            {"suggested_unit_of_measurement": "h"},
        )

    def test_existing_non_legacy_unit_is_preserved(self):
        for unit in ("h", "s", None):
            with self.subTest(unit=unit):
                registry = _Registry(unit)
                self.assertFalse(
                    entity_migrations.migrate_session_duration_unit(
                        registry,
                        "entry-id",
                    )
                )
                self.assertEqual(registry.updates, [])

    def test_missing_entity_is_ignored(self):
        registry = _Registry(exists=False)
        self.assertFalse(
            entity_migrations.migrate_session_duration_unit(
                registry,
                "entry-id",
            )
        )
        self.assertEqual(registry.updates, [])

    def test_entity_from_another_entry_is_ignored(self):
        registry = _Registry()
        registry.entity.unique_id = "different-entry_last_session_duration"
        self.assertFalse(
            entity_migrations.migrate_session_duration_unit(
                registry,
                "entry-id",
            )
        )
        self.assertEqual(registry.updates, [])

    def test_redundant_external_meter_readbacks_are_disabled_once(self):
        registry = _ExternalMeterRegistry()
        expected = []
        for suffix in (
            "external_meter_external_sampling_wiring",
            "external_meter_power_meter_type",
            "external_meter_power_meter_address",
        ):
            expected.append(registry.add(suffix).entity_id)
        registry.add("unrelated_sensor")

        changed = entity_migrations.disable_redundant_external_meter_readbacks(
            registry,
            "entry-id",
            "integration",
        )

        self.assertEqual(changed, tuple(expected))
        self.assertEqual(
            registry.updates,
            [
                (entity_id, {"disabled_by": "integration"})
                for entity_id in expected
            ],
        )

    def test_existing_disabled_readback_is_preserved(self):
        registry = _ExternalMeterRegistry()
        registry.add(
            "external_meter_power_meter_type",
            disabled_by="user",
        )

        self.assertEqual(
            entity_migrations.disable_redundant_external_meter_readbacks(
                registry,
                "entry-id",
                "integration",
            ),
            (),
        )
        self.assertEqual(registry.updates, [])

    def test_migration_runs_before_platform_setup_without_reload(self):
        source = INIT_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "migrate_session_duration_unit(registry, entry.entry_id)",
            source,
        )
        self.assertNotIn(
            "_reload_after_entity_migration",
            source,
        )

    def test_setup_closes_server_when_platform_setup_fails(self):
        source = INIT_PATH.read_text(encoding="utf-8")
        self.assertIn("except Exception:\n        startup_check_task.cancel()", source)
        self.assertIn("await startup_check_task", source)
        self.assertIn("server.close()\n        await server.wait_closed()", source)

    def test_failed_legacy_migration_marker_is_recovered(self):
        source = INIT_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "entry.version < CONFIG_ENTRY_VERSION or has_legacy_marker",
            source,
        )
        self.assertIn(
            "migrated_data.pop(LEGACY_SESSION_DURATION_UNIT_MIGRATION, None)",
            source,
        )
        setup_start = source.index("async def async_setup_entry")
        recovery_call = source.index(
            "await _recover_pending_entity_migrations(hass, entry)",
            setup_start,
        )
        server_start = source.index("await start_ocpp_server", setup_start)
        self.assertLess(recovery_call, server_start)
        self.assertNotIn("async_wait_loaded", source)

    def test_config_entry_version_retries_the_registry_migration(self):
        const_source = (COMPONENT_PATH / "const.py").read_text(encoding="utf-8")
        self.assertIn("CONFIG_ENTRY_VERSION = 10", const_source)
        source = INIT_PATH.read_text(encoding="utf-8")
        self.assertIn("disable_redundant_external_meter_readbacks(", source)
        self.assertIn(
            "migrated_data[PENDING_EXTERNAL_METER_READBACK_MIGRATION] = True",
            source,
        )
        platform_setup = source.index(
            "await hass.config_entries.async_forward_entry_setups"
        )
        completion = source.index(
            "_complete_external_meter_readback_migration(hass, entry)",
            platform_setup,
        )
        self.assertGreater(completion, platform_setup)


if __name__ == "__main__":
    unittest.main()
