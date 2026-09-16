"""Regression tests for config-entry and OCPP connection ownership."""
from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import sys
import unittest


PACKAGE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
)
MODULE_PATH = PACKAGE_PATH / "runtime_ownership.py"
SPEC = importlib.util.spec_from_file_location(
    "growatt_thor_runtime_ownership_test_target",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
ownership = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ownership
SPEC.loader.exec_module(ownership)


class RuntimeOwnershipDecisionTest(unittest.TestCase):
    """Exercise the safety policy without Home Assistant or OCPP dependencies."""

    def test_only_one_config_entry_can_claim_the_global_runtime(self):
        runtime_data = {}

        self.assertTrue(ownership.claim_runtime_entry(runtime_data, "entry-a"))
        self.assertFalse(ownership.claim_runtime_entry(runtime_data, "entry-b"))
        self.assertFalse(ownership.claim_runtime_entry(runtime_data, "entry-a"))
        self.assertTrue(ownership.runtime_entry_is_owner(runtime_data, "entry-a"))
        self.assertFalse(ownership.runtime_entry_is_owner(runtime_data, "entry-b"))

    def test_superseded_socket_cannot_release_the_replacement(self):
        old_charge_point = object()
        new_charge_point = object()
        runtime_data = {"charge_point": new_charge_point}

        self.assertFalse(
            ownership.release_active_charge_point(
                runtime_data,
                old_charge_point,
            )
        )
        self.assertIs(runtime_data["charge_point"], new_charge_point)
        self.assertTrue(
            ownership.release_active_charge_point(
                runtime_data,
                new_charge_point,
            )
        )
        self.assertNotIn("charge_point", runtime_data)

    def test_first_charger_claims_an_unassigned_runtime(self):
        self.assertEqual(
            ownership.decide_charge_point_connection(
                retained_charge_point_id=None,
                active_charge_point_id=None,
                incoming_charge_point_id="THOR-A",
            ),
            ownership.ChargePointConnectionDecision.ACCEPT_FIRST,
        )

    def test_same_charger_can_reconnect_after_disconnect(self):
        self.assertEqual(
            ownership.decide_charge_point_connection(
                retained_charge_point_id="THOR-A",
                active_charge_point_id=None,
                incoming_charge_point_id="THOR-A",
            ),
            ownership.ChargePointConnectionDecision.ACCEPT_RECONNECT,
        )

    def test_new_socket_can_replace_only_the_same_active_charger(self):
        self.assertEqual(
            ownership.decide_charge_point_connection(
                retained_charge_point_id="THOR-A",
                active_charge_point_id="THOR-A",
                incoming_charge_point_id="THOR-A",
            ),
            ownership.ChargePointConnectionDecision.REPLACE_SAME_CHARGER,
        )

    def test_different_charger_is_rejected_while_one_is_active(self):
        self.assertEqual(
            ownership.decide_charge_point_connection(
                retained_charge_point_id="THOR-A",
                active_charge_point_id="THOR-A",
                incoming_charge_point_id="THOR-B",
            ),
            ownership.ChargePointConnectionDecision.REJECT_DIFFERENT_CHARGER,
        )

    def test_retained_identity_blocks_silent_charger_swap_after_disconnect(self):
        self.assertEqual(
            ownership.decide_charge_point_connection(
                retained_charge_point_id="THOR-A",
                active_charge_point_id=None,
                incoming_charge_point_id="THOR-B",
            ),
            ownership.ChargePointConnectionDecision.REJECT_DIFFERENT_CHARGER,
        )


class RuntimeOwnershipWiringTest(unittest.TestCase):
    """Keep the pure ownership policy connected to runtime entry points."""

    def test_config_flow_aborts_when_an_entry_already_exists(self):
        tree = ast.parse((PACKAGE_PATH / "config_flow.py").read_text())
        flow_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "GrowattThorConfigFlow"
        )
        user_step = next(
            node
            for node in flow_class.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "async_step_user"
        )
        called_names = {
            node.func.attr
            for node in ast.walk(user_step)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }

        self.assertIn("_async_current_entries", called_names)
        self.assertIn("async_abort", called_names)

    def test_runtime_claim_precedes_coordinator_publication(self):
        tree = ast.parse((PACKAGE_PATH / "__init__.py").read_text())
        setup = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "async_setup_entry"
        )
        claim_call = next(
            node
            for node in ast.walk(setup)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "claim_runtime_entry"
        )
        coordinator_assignment = next(
            node
            for node in ast.walk(setup)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Subscript)
                and isinstance(target.slice, ast.Constant)
                and target.slice.value == "coordinator"
                for target in node.targets
            )
        )

        self.assertLess(claim_call.lineno, coordinator_assignment.lineno)

    def test_non_owner_unload_is_guarded_before_runtime_cleanup(self):
        tree = ast.parse((PACKAGE_PATH / "__init__.py").read_text())
        unload = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "async_unload_entry"
        )
        owner_check = next(
            node
            for node in ast.walk(unload)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "runtime_entry_is_owner"
        )
        clear_call = next(
            node
            for node in ast.walk(unload)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "clear"
        )

        self.assertLess(owner_check.lineno, clear_call.lineno)

    def test_connection_decision_precedes_charge_point_construction(self):
        tree = ast.parse((PACKAGE_PATH / "ocpp_server.py").read_text())
        connect = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_on_connect"
        )
        decision_call = next(
            node
            for node in ast.walk(connect)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "decide_charge_point_connection"
        )
        constructor_call = next(
            node
            for node in ast.walk(connect)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "GrowattChargePoint"
        )

        self.assertLess(decision_call.lineno, constructor_call.lineno)

    def test_every_inbound_handler_checks_current_connection_ownership(self):
        tree = ast.parse((PACKAGE_PATH / "ocpp_server.py").read_text())
        charge_point_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "GrowattChargePoint"
        )
        handlers = [
            node
            for node in charge_point_class.body
            if isinstance(node, ast.AsyncFunctionDef)
            and any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Name)
                and decorator.func.id == "on"
                for decorator in node.decorator_list
            )
        ]

        self.assertGreater(len(handlers), 0)
        for handler in handlers:
            guard_calls = [
                node
                for node in ast.walk(handler)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_connection_may_update_coordinator"
            ]
            with self.subTest(handler=handler.name):
                self.assertGreaterEqual(len(guard_calls), 1)
                if handler.name == "on_start_transaction":
                    # Allocation awaits a lock, so ownership must be checked a
                    # second time before the transaction state is committed.
                    self.assertGreaterEqual(len(guard_calls), 2)

    def test_watchdog_and_handler_cleanup_release_by_object_identity(self):
        tree = ast.parse((PACKAGE_PATH / "ocpp_server.py").read_text())
        release_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "release_active_charge_point"
        ]

        # One call belongs to the watchdog and one to _on_connect's finalizer.
        self.assertGreaterEqual(len(release_calls), 2)

    def test_single_instance_abort_is_translated_in_every_language(self):
        translations = PACKAGE_PATH / "translations"
        files = sorted(translations.glob("*.json"))
        self.assertGreater(len(files), 0)
        for path in files:
            payload = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(language=path.stem):
                self.assertTrue(
                    payload["config"]["abort"]["single_instance_allowed"]
                )


if __name__ == "__main__":
    unittest.main()
