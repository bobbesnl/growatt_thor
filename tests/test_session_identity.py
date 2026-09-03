"""Tests for stable source-aware session identities."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import sys
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
    / "session_identity.py"
)
SPEC = importlib.util.spec_from_file_location(
    "growatt_thor_session_identity_test_target",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
session_identity = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = session_identity
SPEC.loader.exec_module(session_identity)


class SessionIdentityTest(unittest.TestCase):
    """Verify deterministic IDs and source namespace separation."""

    def _build(self, **overrides):
        values = {
            "source": session_identity.SOURCE_HOME_ASSISTANT,
            "source_instance_id": "config-entry-1",
            "charge_point_id": "XGJ0000322340519",
            "transaction_id": 7,
            "started_at": "2026-08-24T10:00:00Z",
            "ended_at": "2026-08-24T10:30:00Z",
            "record_id": 346,
        }
        values.update(overrides)
        return session_identity.build_session_id(**values)

    def test_same_identity_fields_produce_same_compact_id(self):
        session_id = self._build()

        self.assertEqual(session_id, self._build())
        self.assertRegex(session_id, re.compile(r"^ha-[a-f0-9]{16}$"))

    def test_reused_transaction_id_is_disambiguated_by_start_time(self):
        self.assertNotEqual(
            self._build(started_at="2026-08-24T10:00:00Z"),
            self._build(started_at="2026-08-25T10:00:00Z"),
        )

    def test_home_assistant_instances_have_separate_namespaces(self):
        self.assertNotEqual(
            self._build(source_instance_id="config-entry-1"),
            self._build(source_instance_id="config-entry-2"),
        )

    def test_home_assistant_id_stays_stable_as_completion_data_arrives(self):
        active_id = self._build(ended_at=None, record_id=None)
        completed_id = self._build(
            ended_at="2026-08-24T10:30:00Z",
            record_id=346,
        )

        self.assertEqual(active_id, completed_id)

    def test_external_and_legacy_sources_are_explicit(self):
        external_id = self._build(
            source=session_identity.SOURCE_EXTERNAL_OR_UNKNOWN,
            source_instance_id=None,
        )
        legacy_id = self._build(
            source=session_identity.SOURCE_LEGACY_UNKNOWN,
            source_instance_id=None,
        )

        self.assertRegex(external_id, re.compile(r"^ext-[a-f0-9]{16}$"))
        self.assertRegex(legacy_id, re.compile(r"^legacy-[a-f0-9]{16}$"))
        self.assertNotEqual(external_id, legacy_id)

    def test_external_id_stays_stable_as_completion_data_arrives(self):
        active_id = self._build(
            source=session_identity.SOURCE_EXTERNAL_OR_UNKNOWN,
            source_instance_id=None,
            ended_at=None,
            record_id=345,
        )
        completed_id = self._build(
            source=session_identity.SOURCE_EXTERNAL_OR_UNKNOWN,
            source_instance_id=None,
            ended_at="2026-08-24T10:30:00Z",
            record_id=346,
        )

        self.assertEqual(active_id, completed_id)

    def test_unknown_source_falls_back_without_claiming_ownership(self):
        session_id = self._build(source="cloud")

        self.assertTrue(session_id.startswith("ext-"))


if __name__ == "__main__":
    unittest.main()
