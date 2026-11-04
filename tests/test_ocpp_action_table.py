"""Every OCPP action the integration sends has one declared timeout policy."""

import ast
import importlib.util
import inspect
import unittest
from pathlib import Path

from tests.support import load_package_module

PACKAGE_PATH = Path(__file__).parents[1] / "custom_components" / "growatt_thor"
SERVER_PATH = PACKAGE_PATH / "ocpp/growatt/server.py"
TARGET_OPERATIONS_PATH = PACKAGE_PATH / "targets/charger_ops.py"

actions = load_package_module("ocpp.growatt.actions")
Retry = actions.OcppRetry


def _call(node):
    return node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")


def _operation_name(node):
    """The action part of a literal or f-string operation name."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.JoinedStr) and isinstance(node.values[0], ast.Constant):
        return node.values[0].value.split("(")[0]
    raise AssertionError(f"Unexpected operation name {ast.dump(node)}")


class OcppActionTableTest(unittest.TestCase):
    def test_declared_policies_match_the_firmware_limits(self):
        expected = {
            "TriggerMessage(StatusNotification)": (30, False, Retry.NEXT_POLL),
            "TriggerMessage(BootNotification)": (30, False, Retry.RECONNECT),
            "GetConfiguration": (30.0, False, Retry.RECONNECT),
            "DataTransfer(get_external_meterval)": (15.0, False, Retry.BACKOFF),
            "ChangeConfiguration": (30, True, Retry.NONE),
            "DataTransfer": (30, True, Retry.NONE),
            "RemoteStartTransaction": (30, True, Retry.NONE),
            "RemoteStopTransaction": (30, True, Retry.NONE),
            "ReserveNow": (30, True, Retry.NONE),
            "CancelReservation": (30, True, Retry.NONE),
        }
        self.assertEqual(
            {
                name: (
                    policy.response_timeout,
                    policy.timeout_makes_outcome_uncertain,
                    policy.retry,
                )
                for name, policy in actions.OCPP_ACTIONS.items()
            },
            expected,
        )

    @unittest.skipIf(importlib.util.find_spec("ocpp") is None, "ocpp library not installed")
    def test_library_default_is_the_declared_response_timeout(self):
        from ocpp.charge_point import ChargePoint

        default = inspect.signature(ChargePoint.__init__).parameters["response_timeout"].default
        self.assertEqual(default, actions.OCPP_RESPONSE_TIMEOUT_SECONDS)

    def test_every_sent_action_has_a_policy(self):
        server = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
        serialized = {
            _operation_name(node.args[0])
            for node in ast.walk(server)
            if isinstance(node, ast.Call) and _call(node) == "_run_serialized_request"
        }
        looked_up = {
            node.args[0].value
            for node in ast.walk(server)
            if isinstance(node, ast.Call)
            and _call(node) == "_uncertain"
            and isinstance(node.args[0], ast.Constant)
        }
        targets = ast.parse(TARGET_OPERATIONS_PATH.read_text(encoding="utf-8"))
        direct = {
            node.args[0].func.attr
            for node in ast.walk(targets)
            if isinstance(node, ast.Call)
            and _call(node) == "call"
            and node.args
            and isinstance(node.args[0], ast.Call)
            and isinstance(node.args[0].func, ast.Attribute)
        }

        self.assertTrue(serialized and direct)
        self.assertLessEqual(serialized | looked_up | direct, set(actions.OCPP_ACTIONS))
        # Each serialized request takes its uncertainty rule from the table.
        self.assertEqual(serialized, looked_up)

    def test_server_takes_timeouts_from_the_table(self):
        source = SERVER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        timeouts = [
            keyword.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for keyword in node.keywords
            if keyword.arg in {"timeout", "response_timeout"}
        ]
        table_reads = [
            node
            for node in timeouts
            if (isinstance(node, ast.Attribute) and node.attr == "response_timeout")
            or (isinstance(node, ast.Name) and node.id == "OCPP_RESPONSE_TIMEOUT_SECONDS")
        ]
        # The remaining bounds are websocket close handshakes, not OCPP actions.
        others = [node for node in timeouts if node not in table_reads]
        self.assertEqual(len(table_reads), 3)
        self.assertTrue(
            all(
                isinstance(node, ast.Name) and node.id == "WEBSOCKET_CLOSE_TIMEOUT_SECONDS"
                for node in others
            )
        )


if __name__ == "__main__":
    unittest.main()
