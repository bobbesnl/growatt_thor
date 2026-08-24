"""Tests for Home Assistant currency-derived entity units."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
    / "currency.py"
)
SPEC = importlib.util.spec_from_file_location(
    "growatt_thor_currency_test_target",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
currency = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(currency)


class CurrencyTest(unittest.TestCase):
    """Verify configured currency units and their fallback."""

    def test_uses_home_assistant_currency(self):
        hass = SimpleNamespace(config=SimpleNamespace(currency="usd"))

        self.assertEqual(currency.configured_currency(hass), "USD")
        self.assertEqual(currency.electricity_price_unit(hass), "USD/kWh")

    def test_defaults_to_euro_without_configured_currency(self):
        self.assertEqual(currency.configured_currency(SimpleNamespace()), "EUR")
        self.assertEqual(
            currency.electricity_price_unit(
                SimpleNamespace(config=SimpleNamespace(currency=None))
            ),
            "EUR/kWh",
        )


if __name__ == "__main__":
    unittest.main()
