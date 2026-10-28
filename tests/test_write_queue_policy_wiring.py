"""Charger write-policy and platform wiring contracts."""

from __future__ import annotations

import ast
import unittest

from tests.support import (
    PACKAGE_PATH,
    load_package_module,
)

write_queue_module = load_package_module("runtime.write_results")


class WriteQueuePolicyWiringTest(unittest.TestCase):
    """Keep production call sites explicit about delayed-command semantics."""

    PRODUCTION_FILES = (
        "button.py",
        "charging/commands.py",
        "config_flow.py",
        "configuration/controls.py",
        "number.py",
        "select.py",
        "switch.py",
        "time.py",
    )

    def test_bundled_policy_windows_are_deliberate_and_bounded(self):
        self.assertEqual(
            write_queue_module.CONFIGURATION_WRITE_POLICY.expires_after,
            300.0,
        )
        self.assertEqual(
            write_queue_module.TRANSACTION_CONTROL_WRITE_POLICY.expires_after,
            60.0,
        )
        self.assertEqual(
            write_queue_module.VOLATILE_CONTROL_WRITE_POLICY.expires_after,
            15.0,
        )
        self.assertEqual(
            write_queue_module.VOLATILE_CONTROL_WRITE_POLICY.reconnect,
            write_queue_module.ChargerWriteReconnectPolicy.DISCARD_WHEN_DISCONNECTED,
        )

        for invalid_expiry in (0, float("nan")):
            with self.subTest(invalid_expiry=invalid_expiry):
                with self.assertRaisesRegex(ValueError, "greater than zero"):
                    write_queue_module.ChargerWriteQueuePolicy(
                        expires_after=invalid_expiry,
                        reconnect=(
                            write_queue_module.ChargerWriteReconnectPolicy.RETAIN_UNTIL_EXPIRY
                        ),
                    )

    def test_every_production_queue_call_declares_a_policy(self):
        missing = []
        for filename in self.PRODUCTION_FILES:
            tree = ast.parse((PACKAGE_PATH / filename).read_text())
            for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
                if not (isinstance(call.func, ast.Attribute) and call.func.attr == "queue_write"):
                    continue
                keyword_names = {keyword.arg for keyword in call.keywords}
                if "policy" not in keyword_names:
                    missing.append(f"{filename}:{call.lineno}")

        self.assertEqual(missing, [])

    def test_start_stop_and_ap_mode_use_their_specific_policies(self):
        expected = {
            ("button.py", "REMOTE_START_COMMAND"): (
                "VOLATILE_CONTROL_WRITE_POLICY",
                True,
            ),
            ("charging/commands.py", "REMOTE_STOP_COMMAND"): (
                "TRANSACTION_CONTROL_WRITE_POLICY",
                True,
            ),
            ("config_flow.py", "DataTransfer(appconfigmode)"): (
                "VOLATILE_CONTROL_WRITE_POLICY",
                False,
            ),
        }

        found = {}
        for filename in {item[0] for item in expected}:
            tree = ast.parse((PACKAGE_PATH / filename).read_text())
            for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
                if not (isinstance(call.func, ast.Attribute) and call.func.attr == "queue_write"):
                    continue
                keywords = {
                    keyword.arg: keyword.value
                    for keyword in call.keywords
                    if keyword.arg is not None
                }
                command = keywords.get("command_name")
                policy = keywords.get("policy")
                if not isinstance(policy, ast.Name):
                    continue
                if isinstance(command, ast.Constant):
                    command_identifier = command.value
                elif isinstance(command, ast.Name):
                    command_identifier = command.id
                else:
                    continue
                key = (filename, command_identifier)
                if key in expected:
                    found[key] = (
                        policy.id,
                        "revalidate" in keywords,
                    )

        self.assertEqual(found, expected)

    def test_stop_no_longer_invents_transaction_zero(self):
        tree = ast.parse((PACKAGE_PATH / "charging/commands.py").read_text())
        stop_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "StopChargingCommand"
        )
        integer_constants = [
            node.value
            for node in ast.walk(stop_class)
            if isinstance(node, ast.Constant) and type(node.value) is int
        ]
        attributes = [node.attr for node in ast.walk(stop_class) if isinstance(node, ast.Attribute)]

        self.assertNotIn(0, integer_constants)
        self.assertIn("transaction_id", attributes)
        self.assertIn("transaction_is_active", attributes)

    def test_start_and_stop_share_one_opposing_intent_queue_lane(self):
        tree = ast.parse(
            (PACKAGE_PATH / "button.py").read_text()
            + "\n"
            + (PACKAGE_PATH / "charging/commands.py")
            .read_text()
            .replace("from __future__ import annotations", "")
        )
        classes = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name in {"StartChargingButton", "StopChargingCommand"}
        }

        for class_name in classes:
            queue_call = next(
                node
                for node in ast.walk(classes[class_name])
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "queue_write"
            )
            keywords = {
                keyword.arg: keyword.value
                for keyword in queue_call.keywords
                if keyword.arg is not None
            }
            dedupe_key = keywords["dedupe_key"]
            with self.subTest(class_name=class_name):
                self.assertIsInstance(dedupe_key, ast.Name)
                self.assertEqual(
                    dedupe_key.id,
                    "SESSION_CONTROL_DEDUPE_KEY",
                )

        stop_calls = {
            node.func.attr: node
            for node in ast.walk(classes["StopChargingCommand"])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        cancellation = stop_calls["cancel_queued_writes"]
        cancellation_keywords = {
            keyword.arg: keyword.value
            for keyword in cancellation.keywords
            if keyword.arg is not None
        }
        self.assertEqual(
            cancellation_keywords["command_name"].id,
            "REMOTE_START_COMMAND",
        )
        self.assertEqual(
            cancellation_keywords["reason"].id,
            "STOP_CANCELLED_START_REASON",
        )
