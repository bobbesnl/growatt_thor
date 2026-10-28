"""Tests for Home Assistant currency-derived entity units."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from tests.support import PACKAGE_PATH, load_package_module

MODULE_PATH = PACKAGE_PATH / "energy/currency.py"
currency = load_package_module("growatt_thor_currency_test_target", MODULE_PATH)


class CurrencyTest(unittest.TestCase):
    """Verify configured currency units and their fallback."""

    def test_uses_home_assistant_currency(self):
        hass = SimpleNamespace(config=SimpleNamespace(currency="usd"))

        self.assertEqual(currency.configured_currency(hass), "USD")
        self.assertEqual(currency.electricity_price_unit(hass), "USD/kWh")

    def test_defaults_to_euro_without_configured_currency(self):
        self.assertEqual(currency.configured_currency(SimpleNamespace()), "EUR")
        self.assertEqual(
            currency.electricity_price_unit(SimpleNamespace(config=SimpleNamespace(currency=None))),
            "EUR/kWh",
        )


if __name__ == "__main__":
    unittest.main()
