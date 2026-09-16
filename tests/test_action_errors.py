"""Regression tests for Home Assistant action-error reporting."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


PACKAGE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
)


class _HomeAssistantError(Exception):
    """Small stand-in retaining Home Assistant's localization arguments."""

    def __init__(
        self,
        *,
        translation_domain=None,
        translation_key=None,
        translation_placeholders=None,
    ):
        super().__init__(translation_key)
        self.translation_domain = translation_domain
        self.translation_key = translation_key
        self.translation_placeholders = translation_placeholders


class _ServiceValidationError(_HomeAssistantError):
    """Stand-in used to distinguish user input from communication errors."""


def _load_action_errors():
    package_name = "growatt_thor_action_error_test_target"
    package = types.ModuleType(package_name)
    package.__path__ = [str(PACKAGE_PATH)]
    exceptions = types.ModuleType("homeassistant.exceptions")
    exceptions.HomeAssistantError = _HomeAssistantError
    exceptions.ServiceValidationError = _ServiceValidationError

    with patch.dict(
        sys.modules,
        {
            package_name: package,
            "homeassistant": types.ModuleType("homeassistant"),
            "homeassistant.exceptions": exceptions,
        },
    ):
        spec = importlib.util.spec_from_file_location(
            f"{package_name}.action_errors",
            PACKAGE_PATH / "action_errors.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return module


action_errors = _load_action_errors()


class ActionErrorMappingTest(unittest.TestCase):
    """Verify stable HA exception classes, keys, and placeholders."""

    def assert_localized_error(self, reason, exception_type, translation_key):
        with self.assertRaises(exception_type) as raised:
            action_errors.raise_write_blocked(reason)
        self.assertEqual(raised.exception.translation_domain, "growatt_thor")
        self.assertEqual(raised.exception.translation_key, translation_key)
        return raised.exception

    def test_disconnect_is_a_communication_error(self):
        self.assert_localized_error(
            "charger_disconnected",
            _HomeAssistantError,
            "charger_disconnected",
        )

    def test_known_state_guards_are_validation_errors(self):
        for reason in (
            "charger_faulted",
            "active_transaction",
            "control_not_applicable",
            "configuration_read_only",
        ):
            with self.subTest(reason=reason):
                error = self.assert_localized_error(
                    reason,
                    _ServiceValidationError,
                    reason,
                )
                self.assertIsNone(error.translation_placeholders)

    def test_unknown_reason_fails_closed_without_losing_diagnostics(self):
        error = self.assert_localized_error(
            "future_guard",
            _ServiceValidationError,
            "action_not_allowed",
        )
        self.assertEqual(
            error.translation_placeholders,
            {"reason": "future_guard"},
        )

    def test_specific_validation_error_stringifies_placeholders(self):
        with self.assertRaises(_ServiceValidationError) as raised:
            action_errors.raise_action_validation(
                "value_out_of_range",
                placeholders={"value": 64, "minimum": 6, "maximum": 32},
            )
        self.assertEqual(raised.exception.translation_domain, "growatt_thor")
        self.assertEqual(
            raised.exception.translation_placeholders,
            {"value": "64", "minimum": "6", "maximum": "32"},
        )

    def test_runtime_service_failure_is_returned_as_ha_error(self):
        with self.assertRaises(_HomeAssistantError) as raised:
            action_errors.raise_communication_error(
                "refresh_failed",
                placeholders={"step": "configuration"},
            )

        self.assertNotIsInstance(raised.exception, _ServiceValidationError)
        self.assertEqual(raised.exception.translation_domain, "growatt_thor")
        self.assertEqual(raised.exception.translation_key, "refresh_failed")
        self.assertEqual(
            raised.exception.translation_placeholders,
            {"step": "configuration"},
        )


class PublicActionWiringTest(unittest.TestCase):
    """Keep the immediate HA action guards connected to the shared helpers."""

    EXPECTED_HELPERS = {
        ("configuration_control.py", "GrowattConfigurationControlMixin", "_async_write_configuration"): {
            "raise_write_blocked",
            "raise_charger_disconnected",
        },
        ("button.py", "StartChargingButton", "async_press"): {
            "raise_write_blocked",
            "raise_charger_disconnected",
            "raise_action_validation",
        },
        ("button.py", "StopChargingButton", "async_press"): {
            "raise_charger_disconnected",
            "raise_action_validation",
        },
        ("button.py", "ApplyPvLinkageButton", "async_press"): {
            "raise_write_blocked",
            "raise_charger_disconnected",
            "raise_action_validation",
        },
        ("number.py", "MaxCurrentNumber", "async_set_native_value"): {
            "raise_write_blocked",
            "raise_charger_disconnected",
            "raise_action_validation",
        },
        ("number.py", "LoadBalancingLimitNumber", "async_set_native_value"): {
            "raise_write_blocked",
            "raise_charger_disconnected",
        },
        ("number.py", "ElectricityPriceNumber", "async_set_native_value"): {
            "raise_write_blocked",
            "raise_charger_disconnected",
        },
        ("number.py", "PvSmartBoostTargetEnergyNumber", "async_set_native_value"): {
            "raise_write_blocked",
        },
        ("select.py", "WorkingModeSelect", "async_select_option"): {
            "raise_write_blocked",
            "raise_charger_disconnected",
            "raise_action_validation",
        },
        ("select.py", "PvBoostDraftSelect", "async_select_option"): {
            "raise_write_blocked",
        },
        ("switch.py", "LoadBalancingEnableSwitch", "_set_value"): {
            "raise_write_blocked",
            "raise_charger_disconnected",
        },
        ("switch.py", "LcdDisplaySwitch", "_set_value"): {
            "raise_write_blocked",
            "raise_charger_disconnected",
        },
        ("time.py", "BaseAutoChargeTime", "async_set_value"): {
            "raise_write_blocked",
            "raise_charger_disconnected",
        },
        ("time.py", "BasePvBoostTime", "async_set_value"): {
            "raise_write_blocked",
        },
    }

    def test_public_action_guards_raise_instead_of_silently_returning(self):
        parsed_files = {}
        for file_name, class_name, method_name in self.EXPECTED_HELPERS:
            tree = parsed_files.setdefault(
                file_name,
                ast.parse((PACKAGE_PATH / file_name).read_text(encoding="utf-8")),
            )
            class_node = next(
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == class_name
            )
            method = next(
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == method_name
            )
            calls = {
                node.func.id
                for node in ast.walk(method)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
            with self.subTest(class_name=class_name, method_name=method_name):
                self.assertTrue(
                    self.EXPECTED_HELPERS[
                        (file_name, class_name, method_name)
                    ].issubset(calls)
                )


if __name__ == "__main__":
    unittest.main()
