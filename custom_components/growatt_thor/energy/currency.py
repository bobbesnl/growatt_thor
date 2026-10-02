"""Currency helpers for charger price and session cost entities."""
from __future__ import annotations


DEFAULT_CURRENCY = "EUR"
_CURRENCY_SYMBOLS = {"EUR": "€"}


def configured_currency(hass) -> str:
    """Return Home Assistant's configured currency with a stable fallback."""
    config = getattr(hass, "config", None)
    currency = getattr(config, "currency", None)
    if not currency:
        return DEFAULT_CURRENCY
    return str(currency).upper()


def electricity_price_unit(hass) -> str:
    """Return the configured currency per kWh unit."""
    return f"{configured_currency(hass)}/kWh"


def normalized_price_unit(unit: object, currency: str) -> str | None:
    """Normalize a price unit without converting the sensor's numeric value.

    A symbol is accepted only for the configured HA currency. In particular,
    ``€/kWh`` and ``EUR/kWh`` describe the same price, while a sensor using a
    different currency must not silently feed the cost accumulator.
    """
    if not isinstance(unit, str):
        return None
    unit = unit.strip()
    currency = currency.upper()
    symbol = _CURRENCY_SYMBOLS.get(currency)
    if unit == f"{currency}/kWh" or (symbol is not None and unit == f"{symbol}/kWh"):
        return f"{currency}/kWh"
    return None
