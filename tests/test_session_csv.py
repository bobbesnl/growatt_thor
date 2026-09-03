"""Tests for backward-compatible session CSV handling."""
from __future__ import annotations

import csv
import importlib.util
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest


COMPONENT_PATH = (
    Path(__file__).parents[1] / "custom_components" / "growatt_thor"
)
PACKAGE_NAME = "growatt_thor_session_csv_test_package"
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


_load_module(f"{PACKAGE_NAME}.session_identity", "session_identity.py")
session_csv = _load_module(
    f"{PACKAGE_NAME}.session_csv",
    "session_csv.py",
)


LEGACY_HEADERS = session_csv.SESSION_LOG_HEADERS[:-2]


def _row(**overrides):
    row = {
        "timestamp": "2026-08-24T10:31:00Z",
        "charger_id": "XGJ0000322340519",
        "location": "Home",
        "start_time": "2026-08-24 10:00:00",
        "end_time": "2026-08-24 10:30:00",
        "energy_kwh": "0.412",
        "cost": "0.09",
        "duration_minutes": "30.0",
        "transaction_id": "7",
    }
    row.update(overrides)
    return row


class SessionCsvTest(unittest.TestCase):
    """Verify new files and in-place migration of historical logs."""

    def test_new_log_keeps_supplied_source_aware_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.csv"
            session_csv.append_session_row(
                path,
                _row(
                    session_id="ha-0123456789abcdef",
                    session_source="home_assistant",
                ),
            )

            with path.open(newline="", encoding="utf-8") as source:
                reader = csv.DictReader(source)
                rows = list(reader)

            self.assertEqual(reader.fieldnames, session_csv.SESSION_LOG_HEADERS)
            self.assertEqual(rows[0]["session_id"], "ha-0123456789abcdef")
            self.assertEqual(rows[0]["session_source"], "home_assistant")

    def test_legacy_log_is_migrated_before_new_row_is_appended(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.csv"
            with path.open("w", newline="", encoding="utf-8") as target:
                writer = csv.DictWriter(target, fieldnames=LEGACY_HEADERS)
                writer.writeheader()
                writer.writerow(_row())
            path.chmod(0o640)

            session_csv.append_session_row(
                path,
                _row(
                    transaction_id="8",
                    session_id="ext-fedcba9876543210",
                    session_source="external_or_unknown",
                ),
            )

            with path.open(newline="", encoding="utf-8") as source:
                reader = csv.DictReader(source)
                rows = list(reader)

            self.assertEqual(reader.fieldnames, session_csv.SESSION_LOG_HEADERS)
            self.assertTrue(rows[0]["session_id"].startswith("legacy-"))
            self.assertEqual(rows[0]["session_source"], "legacy_unknown")
            self.assertEqual(rows[1]["session_id"], "ext-fedcba9876543210")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)

    def test_migration_preserves_unknown_existing_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.csv"
            headers = [*LEGACY_HEADERS, "custom"]
            with path.open("w", newline="", encoding="utf-8") as target:
                writer = csv.DictWriter(target, fieldnames=headers)
                writer.writeheader()
                writer.writerow(_row(custom="retained"))

            session_csv.append_session_row(path, _row(transaction_id="8"))

            with path.open(newline="", encoding="utf-8") as source:
                reader = csv.DictReader(source)
                rows = list(reader)

            self.assertIn("custom", reader.fieldnames)
            self.assertEqual(rows[0]["custom"], "retained")

    def test_legacy_identity_is_deterministic(self):
        first = session_csv.normalize_session_row(_row())
        second = session_csv.normalize_session_row(_row())

        self.assertEqual(first["session_id"], second["session_id"])
        self.assertEqual(first["session_source"], "legacy_unknown")


if __name__ == "__main__":
    unittest.main()
