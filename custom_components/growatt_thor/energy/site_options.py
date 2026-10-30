"""Pure validation of site-accounting option drafts."""

from collections.abc import Mapping
from math import isfinite
from typing import Protocol

from ..const import CONF_SITE_GRID_SOURCE
from .currency import normalized_price_unit
from .options import (
    CONF_BATTERY_POWER_ENTITY,
    CONF_FIXED_PRICE,
    CONF_GRID_ENTITY,
    CONF_GRID_SIGN,
    CONF_HOUSE_ENTITY,
    CONF_SITE_PROFILE,
    CONF_SOLAR_ENTITY,
    CONF_TARIFF_ENTITY,
    SITE_GRID_SOURCES,
)
from .site_inputs import GRID_SIGNS, AccountingProfile
from .sources import duplicate_source_fields, is_power_sensor
from .stop_guard_policy import (
    AUTO_STOP_MODES,
    CONF_AUTO_STOP_MODE,
    CONF_STOP_HOLD,
    CONF_STOP_THRESHOLD,
    STOP_HOLD_RANGE,
    STOP_HOLD_SECONDS,
    STOP_THRESHOLD_RANGE,
    STOP_THRESHOLD_W,
)


class StateLookup(Protocol):
    def get(self, entity_id: str) -> object | None: ...


def profile_requires_battery(profile: object) -> bool:
    return profile in ("pv_battery", "grohome_load_first")


def validate_site_options(
    user_input: Mapping, current: Mapping, states: StateLookup, *, currency: str = "EUR"
) -> dict[str, str]:
    errors = {}
    profile = user_input.get(CONF_SITE_PROFILE, "disabled")
    if profile not in AccountingProfile:
        errors[CONF_SITE_PROFILE] = "invalid_site_profile"
    auto_stop_mode = user_input.get(CONF_AUTO_STOP_MODE, "off")
    for key, default, low, high in (
        (CONF_STOP_THRESHOLD, STOP_THRESHOLD_W, *STOP_THRESHOLD_RANGE),
        (CONF_STOP_HOLD, STOP_HOLD_SECONDS, *STOP_HOLD_RANGE),
    ):
        value = user_input.get(key, current.get(key, default))
        if not isinstance(value, (int, float)) or not isfinite(value) or not low <= value <= high:
            errors[key] = "invalid_stop_settings"
    if auto_stop_mode not in AUTO_STOP_MODES:
        errors[CONF_AUTO_STOP_MODE] = "invalid_auto_stop_mode"
    elif auto_stop_mode != "off":
        if profile == "disabled":
            errors[CONF_AUTO_STOP_MODE] = "auto_stop_requires_profile"
        elif auto_stop_mode in (
            "battery",
            "battery_or_grid",
        ) and not current.get(CONF_BATTERY_POWER_ENTITY):
            errors[CONF_AUTO_STOP_MODE] = "auto_stop_requires_battery"
    grid_source = user_input.get(CONF_SITE_GRID_SOURCE, "none")
    if auto_stop_mode in ("grid", "battery_or_grid") and grid_source == "none":
        errors[CONF_SITE_GRID_SOURCE] = "grid_source_required"
    if profile in ("pv", "pv_battery", "grohome_load_first") and grid_source == "none":
        errors[CONF_SITE_GRID_SOURCE] = "grid_source_required"
    if grid_source == "ha_sensor" and not user_input.get(CONF_GRID_ENTITY):
        errors[CONF_GRID_ENTITY] = "grid_source_required"
    for key in (CONF_GRID_ENTITY, CONF_SOLAR_ENTITY, CONF_HOUSE_ENTITY):
        entity = user_input.get(key)
        if entity and not is_power_sensor(entity, states.get(entity)):
            errors[key] = "invalid_power_sensor"
    if user_input.get(CONF_GRID_SIGN) not in GRID_SIGNS:
        errors[CONF_GRID_SIGN] = "invalid_grid_sign"
    tariff_entity = user_input.get(CONF_TARIFF_ENTITY)
    if profile != "disabled" and not tariff_entity and user_input.get(CONF_FIXED_PRICE) is None:
        errors[CONF_FIXED_PRICE] = "tariff_required"
    if tariff_entity:
        state = states.get(tariff_entity)
        unit = getattr(state, "attributes", {}).get("unit_of_measurement") if state else None
        if not tariff_entity.startswith("sensor.") or normalized_price_unit(unit, currency) is None:
            errors[CONF_TARIFF_ENTITY] = "invalid_tariff_sensor"
    if grid_source not in SITE_GRID_SOURCES:
        errors[CONF_SITE_GRID_SOURCE] = "invalid_grid_source"
    if profile_requires_battery(profile) and not current.get(CONF_BATTERY_POWER_ENTITY):
        errors[CONF_SITE_PROFILE] = "profile_requires_battery"
    if profile != "disabled":
        assignments = {
            CONF_BATTERY_POWER_ENTITY: current.get(CONF_BATTERY_POWER_ENTITY),
            CONF_GRID_ENTITY: user_input.get(CONF_GRID_ENTITY)
            if grid_source == "ha_sensor"
            else None,
            CONF_SOLAR_ENTITY: user_input.get(CONF_SOLAR_ENTITY),
            CONF_HOUSE_ENTITY: user_input.get(CONF_HOUSE_ENTITY),
        }
        for key in duplicate_source_fields(assignments) - {CONF_BATTERY_POWER_ENTITY}:
            errors[key] = "duplicate_power_source"
    price = user_input.get(CONF_FIXED_PRICE)
    if price is not None:
        try:
            if not isfinite(float(price)):
                errors[CONF_FIXED_PRICE] = "invalid_fixed_price"
        except (ValueError, TypeError):
            errors[CONF_FIXED_PRICE] = "invalid_fixed_price"
    return errors
