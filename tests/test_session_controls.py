"""Regression tests for Remote Start/Stop transaction decisions."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
    / "session_controls.py"
)
SPEC = importlib.util.spec_from_file_location(
    "growatt_thor_session_controls_test_target",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
session_controls = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(session_controls)


class SessionControlDecisionTest(unittest.TestCase):
    """Keep delayed session commands tied to current charger state."""

    def test_start_is_rejected_for_every_active_transaction_signal(self):
        # The coordinator folds OCPP Charging/Suspended states, a retained
        # transaction object, and a retained ID into this boolean.  Whatever
        # supplied the evidence, Remote Start must fail closed.
        self.assertEqual(
            session_controls.start_revalidation_failure(
                charger_faulted=False,
                transaction_active=True,
            ),
            "charging_already_active",
        )

    def test_start_is_rejected_while_charger_is_faulted(self):
        self.assertEqual(
            session_controls.start_revalidation_failure(
                charger_faulted=True,
                transaction_active=False,
            ),
            "charger_faulted",
        )

    def test_start_is_allowed_only_when_idle_and_healthy(self):
        self.assertIsNone(
            session_controls.start_revalidation_failure(
                charger_faulted=False,
                transaction_active=False,
            )
        )

    def test_stop_remains_valid_for_its_original_active_transaction(self):
        self.assertIsNone(
            session_controls.stop_revalidation_failure(
                expected_transaction_id=42,
                current_transaction_id=42,
                transaction_active=True,
            )
        )

    def test_stop_is_invalid_after_its_transaction_ended(self):
        for current_transaction_id, transaction_active in (
            (None, False),
            (42, False),
        ):
            with self.subTest(
                current_transaction_id=current_transaction_id,
                transaction_active=transaction_active,
            ):
                self.assertEqual(
                    session_controls.stop_revalidation_failure(
                        expected_transaction_id=42,
                        current_transaction_id=current_transaction_id,
                        transaction_active=transaction_active,
                    ),
                    "transaction_ended",
                )

    def test_stop_cannot_migrate_to_a_newer_transaction(self):
        self.assertEqual(
            session_controls.stop_revalidation_failure(
                expected_transaction_id=42,
                current_transaction_id=43,
                transaction_active=True,
            ),
            "transaction_changed",
        )


if __name__ == "__main__":
    unittest.main()
