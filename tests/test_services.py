"""Wiring tests for long-lived Home Assistant integration services."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest


PACKAGE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
)
INIT_PATH = PACKAGE_PATH / "__init__.py"


def _function(tree, name):
    return next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )


class IntegrationServiceWiringTest(unittest.TestCase):
    """Keep service lifetime separate from one config-entry lifetime."""

    def setUp(self):
        self.tree = ast.parse(INIT_PATH.read_text(encoding="utf-8"))

    def test_domain_setup_registers_services_once(self):
        setup = _function(self.tree, "async_setup")
        register = _function(self.tree, "_register_services")
        setup_calls = {
            node.func.id
            for node in ast.walk(setup)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        register_attributes = {
            node.func.attr
            for node in ast.walk(register)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }

        self.assertIn("_register_services", setup_calls)
        self.assertIn("has_service", register_attributes)
        self.assertIn("async_register", register_attributes)

    def test_entry_setup_and_unload_do_not_own_service_registration(self):
        entry_setup = _function(self.tree, "async_setup_entry")
        entry_unload = _function(self.tree, "async_unload_entry")

        for function in (entry_setup, entry_unload):
            attributes = {
                node.func.attr
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
            }
            with self.subTest(function=function.name):
                self.assertNotIn("async_register", attributes)
                self.assertNotIn("async_remove", attributes)

    def test_handlers_translate_refresh_and_export_failures(self):
        register = _function(self.tree, "_register_services")
        nested = {
            node.name: node
            for node in register.body
            if isinstance(node, ast.AsyncFunctionDef)
        }
        refresh_source = ast.unparse(nested["handle_refresh"])
        export_source = ast.unparse(nested["handle_export_sessions"])

        self.assertIn("operations.async_refresh", refresh_source)
        self.assertIn("raise_charger_disconnected", refresh_source)
        self.assertIn("raise_communication_error", refresh_source)
        self.assertIn("operations.async_export", export_source)
        self.assertIn("parse_export_date_range", export_source)
        self.assertIn("raise_action_validation", export_source)
        self.assertIn("raise_communication_error", export_source)

    def test_service_exception_keys_exist_in_every_translation(self):
        expected = {
            "invalid_export_date",
            "invalid_export_date_range",
            "refresh_failed",
            "session_export_failed",
        }
        for path in sorted((PACKAGE_PATH / "translations").glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(language=path.stem):
                self.assertTrue(expected.issubset(payload["exceptions"]))

    def test_status_trigger_participates_in_write_priority_checks(self):
        tree = ast.parse(
            (PACKAGE_PATH / "ocpp_server.py").read_text(encoding="utf-8")
        )
        charge_point = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "GrowattChargePoint"
        )
        trigger = next(
            node
            for node in charge_point.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "trigger_status"
        )
        argument_names = [argument.arg for argument in trigger.args.kwonlyargs]
        run_call = next(
            node
            for node in ast.walk(trigger)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_run_serialized_request"
        )
        keywords = {keyword.arg: keyword.value for keyword in run_call.keywords}

        self.assertIn("skip_if_writes_pending", argument_names)
        self.assertEqual(
            ast.unparse(keywords["skip_if_writes_pending"]),
            "skip_if_writes_pending",
        )


if __name__ == "__main__":
    unittest.main()
