"""Regression tests for config-entry and OCPP connection ownership."""

from __future__ import annotations

import ast
import json
import unittest

from tests.support import PACKAGE_PATH, load_package_module

MODULE_PATH = PACKAGE_PATH / "runtime/ownership.py"
ownership = load_package_module("runtime.ownership")


class RuntimeOwnershipDecisionTest(unittest.TestCase):
    """Exercise the safety policy without Home Assistant or OCPP dependencies."""

    def test_only_one_config_entry_can_claim_a_runtime_mapping(self):
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


class EntryRuntimeTest(unittest.TestCase):
    """Each config entry owns a separate runtime mapping (backlog F09)."""

    def test_two_entries_get_separate_runtimes(self):
        domain_data = {}

        left = ownership.claim_entry_runtime(domain_data, "entry-left")
        right = ownership.claim_entry_runtime(domain_data, "entry-right")

        self.assertIsNotNone(left)
        self.assertIsNotNone(right)
        self.assertIsNot(left, right)
        left["charge_point"] = object()
        self.assertNotIn("charge_point", right)
        self.assertIs(
            ownership.entry_runtime_data(domain_data, "entry-left"),
            left,
        )
        self.assertEqual(
            [entry_id for entry_id, _ in ownership.loaded_entry_runtimes(domain_data)],
            ["entry-left", "entry-right"],
        )

    def test_same_entry_cannot_claim_twice(self):
        domain_data = {}
        first = ownership.claim_entry_runtime(domain_data, "entry-a")

        self.assertIsNone(ownership.claim_entry_runtime(domain_data, "entry-a"))
        self.assertIs(domain_data["entry-a"], first)

    def test_release_only_removes_the_registered_runtime(self):
        domain_data = {}
        left = ownership.claim_entry_runtime(domain_data, "entry-left")
        right = ownership.claim_entry_runtime(domain_data, "entry-right")
        right["coordinator"] = object()

        self.assertFalse(ownership.release_entry_runtime(domain_data, "entry-left", right))
        self.assertTrue(ownership.release_entry_runtime(domain_data, "entry-left", left))
        self.assertIsNone(ownership.entry_runtime_data(domain_data, "entry-left"))
        self.assertIs(domain_data["entry-right"], right)
        self.assertIn("coordinator", right)

    def test_unknown_entry_has_no_runtime(self):
        domain_data = {"stray": {"config_entry_id": "other"}}

        self.assertIsNone(ownership.entry_runtime_data(domain_data, "missing"))
        self.assertIsNone(ownership.entry_runtime_data(domain_data, "stray"))
        self.assertEqual(ownership.loaded_entry_runtimes(domain_data), [])


class RuntimeOwnershipWiringTest(unittest.TestCase):
    """Keep the pure ownership policy connected to runtime entry points."""

    def test_config_flow_rejects_a_port_used_by_another_entry(self):
        tree = ast.parse((PACKAGE_PATH / "config_flow.py").read_text())
        flow_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "GrowattThorConfigFlow"
        )
        user_step = next(
            node
            for node in flow_class.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_step_user"
        )
        called_names = {
            node.func.attr
            for node in ast.walk(user_step)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

        # A second charger is a second entry; only a port that another
        # entry's server already uses is refused.
        self.assertIn("_configured_ports", called_names)
        self.assertNotIn("async_abort", called_names)

    def test_runtime_claim_precedes_coordinator_publication(self):
        tree = ast.parse((PACKAGE_PATH / "__init__.py").read_text())
        setup = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_setup_entry"
        )
        claim_call = next(
            node
            for node in ast.walk(setup)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "claim_entry_runtime"
        )
        coordinator_assignment = next(
            node
            for node in ast.walk(setup)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Subscript)
                and isinstance(target.slice, ast.Name)
                and target.slice.id == "COORDINATOR"
                for target in node.targets
            )
        )

        self.assertLess(claim_call.lineno, coordinator_assignment.lineno)

    def test_non_owner_unload_is_guarded_before_runtime_cleanup(self):
        tree = ast.parse((PACKAGE_PATH / "__init__.py").read_text())
        unload = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_unload_entry"
        )
        owner_check = next(
            node
            for node in ast.walk(unload)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "entry_runtime_data"
        )
        clear_call = next(
            node
            for node in ast.walk(unload)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "release_entry_runtime"
        )

        self.assertLess(owner_check.lineno, clear_call.lineno)

    def test_connection_decision_precedes_charge_point_construction(self):
        tree = ast.parse((PACKAGE_PATH / "ocpp/server.py").read_text())
        connect = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_on_connect"
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
        tree = ast.parse((PACKAGE_PATH / "ocpp/server.py").read_text())
        charge_point_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "GrowattChargePoint"
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
        tree = ast.parse((PACKAGE_PATH / "ocpp/server.py").read_text())
        release_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "release_active_charge_point"
        ]

        # One call belongs to the watchdog and one to _on_connect's finalizer.
        self.assertGreaterEqual(len(release_calls), 2)

    def test_port_conflict_error_is_translated_in_every_language(self):
        translations = PACKAGE_PATH / "translations"
        files = sorted(translations.glob("*.json"))
        self.assertGreater(len(files), 0)
        for path in files:
            payload = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(language=path.stem):
                self.assertTrue(payload["config"]["error"]["port_already_configured"])
                self.assertNotIn(
                    "single_instance_allowed",
                    payload["config"].get("abort", {}),
                )

    def test_no_charger_state_lives_in_a_domain_global_slot(self):
        """Guard against reintroducing hass.data[DOMAIN]["charge_point"] etc."""
        forbidden = (
            'hass.data[DOMAIN]["coordinator"]',
            'hass.data[DOMAIN]["charge_point"]',
            'hass.data[DOMAIN]["skip_polling_until"]',
            'hass.data[DOMAIN]["polling_task"]',
            '.get(DOMAIN, {}).get("charge_point")',
            '.get(DOMAIN, {}).get("coordinator")',
        )
        for path in sorted(PACKAGE_PATH.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                for pattern in forbidden:
                    self.assertNotIn(pattern, source)


if __name__ == "__main__":
    unittest.main()
