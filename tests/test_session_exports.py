"""Expiry applies to public downloads, including those left across restart."""

import os
import tempfile
import unittest
from pathlib import Path

from support import load_package_module

exports = load_package_module(
    "session_exports",
    Path(__file__).parents[1] / "custom_components/growatt_thor/sessions/exports.py",
)


class SessionExportsTest(unittest.TestCase):
    def test_random_names_and_restart_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            first = exports.new_export_path(directory)
            second = exports.new_export_path(directory)
            self.assertNotEqual(first, second)
            old = Path(directory) / "growatt_thor_export_2026-01-01_2026-12-31.csv"
            unrelated = Path(directory) / "history.csv"
            for path in (first, second, old, unrelated):
                path.write_text("private")
                os.utime(path, (1000, 1000))
            os.utime(second, (1900, 1900))
            exports.cleanup_expired_exports(directory, now=1900)
            self.assertFalse(first.exists())
            self.assertFalse(old.exists())
            self.assertTrue(second.exists())
            self.assertTrue(unrelated.exists())
