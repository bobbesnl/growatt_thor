"""Currency helpers for charger price and session cost entities."""
from __future__ import annotations


DEFAULT_CURRENCY = "EUR"


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
