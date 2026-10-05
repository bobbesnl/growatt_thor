"""Site accounting input normalization and bounded transaction checkpoint."""
from __future__ import annotations

from datetime import datetime
from math import isfinite

from .currency import configured_currency
from .tariffs import tariff_from_state
from .observations import SiteObservations, align_accounting_observations, parse_at, read_site_observations
from .accounting import AccountingPolicy, Tariff
from .session_accounting import SessionAccumulator

CONF_SITE_PROFILE = "site_accounting_profile"
CONF_GRID_ENTITY = "site_grid_power_entity"
CONF_GRID_SIGN = "site_grid_power_sign"
CONF_SOLAR_ENTITY = "site_solar_power_entity"
CONF_HOUSE_ENTITY = "site_house_power_entity"
CONF_TARIFF_ENTITY = "site_tariff_entity"
CONF_FIXED_PRICE = "site_fixed_price"
PROFILES = ("disabled", "grid_only", "pv", "pv_battery", "grohome_load_first")
GRID_SIGNS = ("positive_import", "positive_export")


def coverage_percent(totals: dict[str, float]) -> float | None:
    """Cumulative share of EV energy with a classified source."""
    total = totals.get("energy_kwh", 0.0)
    unknown = totals.get("unknown_kwh", 0.0)
    if not isfinite(total) or total <= 0 or not isfinite(unknown):
        return None
    return round(100 * max(0.0, min(total, total - unknown)) / total, 1)


def site_policy(profile: str) -> AccountingPolicy:
    if profile == "grohome_load_first":
        return AccountingPolicy("load_first", topology="pv_battery")
    return AccountingPolicy(topology=profile if profile in ("grid_only", "pv", "pv_battery") else "grid_only")


def site_inputs(coordinator, at: datetime, *, received_at: datetime | None = None) -> tuple[SiteObservations, Tariff, AccountingPolicy] | None:
    """Read configured power observations and the current valid tariff."""
    options = getattr(coordinator, "site_accounting_options", {}) or {}
    profile = options.get(CONF_SITE_PROFILE, "disabled")
    if profile not in PROFILES or profile == "disabled":
        return None
    hass = getattr(coordinator, "hass", None)
    states = getattr(hass, "states", None)

    site = read_site_observations(coordinator, require_recent_report=False)
    if received_at is not None:
        site = align_accounting_observations(site, at, received_at)
    price = options.get(CONF_FIXED_PRICE)
    if options.get(CONF_TARIFF_ENTITY):
        state = states.get(options[CONF_TARIFF_ENTITY]) if states else None
        return site, tariff_from_state(state, configured_currency(hass)), site_policy(profile)
    try:
        price = float(price) if price is not None else None
    except (TypeError, ValueError):
        price = None
    if price is not None and not isfinite(price):
        price = None
    return site, Tariff(price, currency=configured_currency(hass)), site_policy(profile)
