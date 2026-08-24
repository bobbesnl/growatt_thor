"""Mode-aware capabilities for Growatt charging configuration controls."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final, Mapping

from .configuration import ConfigurationValue, configuration_entity_state


class ControlCapability(str, Enum):
    """Describe how safely one setting can be exposed in Home Assistant."""

    WRITABLE = "writable"
    COMPOUND = "compound"
    READ_ONLY = "read_only"


class ChargingControl(str, Enum):
    """Configuration controls whose applicability depends on charger state."""

    LOAD_BALANCING = "load_balancing"
    LOAD_BALANCING_LIMIT = "load_balancing_limit"
    AUTO_CHARGE_SCHEDULE = "auto_charge_schedule"
    SOLAR_MODE = "solar_mode"
    SOLAR_GRID_IMPORT_LIMIT = "solar_grid_import_limit"
    SOLAR_BOOST = "solar_boost"
    SOLAR_THRESHOLD_CURRENT = "solar_threshold_current"
    GRID_OFF_PEAK_CHARGING = "grid_off_peak_charging"
    OFF_PEAK_ENABLE = "off_peak_enable"
    OFF_PEAK_SCHEDULE = "off_peak_schedule"
    OFF_PEAK_CURRENT = "off_peak_current"
    WARM_UP = "warm_up"
    DELAYED_CHARGING = "delayed_charging"


@dataclass(frozen=True, slots=True)
class ControlDefinition:
    """Describe one control and the configuration states it requires."""

    capability: ControlCapability
    configuration_key: str
    working_modes: frozenset[str] = frozenset()
    charger_modes: frozenset[str] = frozenset()
    solar_modes: frozenset[str] = frozenset()


CONTROL_DEFINITIONS: Final[Mapping[ChargingControl, ControlDefinition]] = (
    MappingProxyType(
        {
            ChargingControl.LOAD_BALANCING: ControlDefinition(
                ControlCapability.WRITABLE,
                "G_ExternalLimitPowerEnable",
                working_modes=frozenset({"fast", "off_peak"}),
            ),
            ChargingControl.LOAD_BALANCING_LIMIT: ControlDefinition(
                ControlCapability.WRITABLE,
                "G_ExternalLimitPower",
                working_modes=frozenset({"fast", "off_peak"}),
            ),
            ChargingControl.AUTO_CHARGE_SCHEDULE: ControlDefinition(
                ControlCapability.WRITABLE,
                "G_AutoChargeTime",
                working_modes=frozenset({"fast"}),
            ),
            ChargingControl.SOLAR_MODE: ControlDefinition(
                ControlCapability.WRITABLE,
                "G_SolarMode",
                working_modes=frozenset({"pv_linkage"}),
            ),
            ChargingControl.SOLAR_GRID_IMPORT_LIMIT: ControlDefinition(
                ControlCapability.WRITABLE,
                "G_SolarLimitPower",
                working_modes=frozenset({"pv_linkage"}),
                solar_modes=frozenset({"pv_linkage", "pv_linkage_plus"}),
            ),
            ChargingControl.SOLAR_BOOST: ControlDefinition(
                ControlCapability.COMPOUND,
                "G_SolarBoost",
                working_modes=frozenset({"pv_linkage"}),
                solar_modes=frozenset({"pv_linkage", "pv_linkage_plus"}),
            ),
            ChargingControl.SOLAR_THRESHOLD_CURRENT: ControlDefinition(
                ControlCapability.READ_ONLY,
                "G_SolarThresholdCurr",
                working_modes=frozenset({"pv_linkage"}),
            ),
            ChargingControl.GRID_OFF_PEAK_CHARGING: ControlDefinition(
                ControlCapability.READ_ONLY,
                "G_PeakValleyEnable",
                charger_modes=frozenset({"plug_and_charge"}),
            ),
            ChargingControl.OFF_PEAK_ENABLE: ControlDefinition(
                ControlCapability.WRITABLE,
                "G_OffPeakEnable",
                working_modes=frozenset({"off_peak"}),
            ),
            ChargingControl.OFF_PEAK_SCHEDULE: ControlDefinition(
                ControlCapability.COMPOUND,
                "G_OffPeakTime",
                working_modes=frozenset({"off_peak"}),
            ),
            ChargingControl.OFF_PEAK_CURRENT: ControlDefinition(
                ControlCapability.READ_ONLY,
                "G_OffPeakCurr",
                working_modes=frozenset({"off_peak"}),
            ),
            ChargingControl.WARM_UP: ControlDefinition(
                ControlCapability.WRITABLE,
                "G_FullContinueChargeEnable",
            ),
            ChargingControl.DELAYED_CHARGING: ControlDefinition(
                ControlCapability.READ_ONLY,
                "G_RandDelayChargeTime",
            ),
        }
    )
)


def _state(
    values: Mapping[str, ConfigurationValue],
    key: str,
) -> object:
    return configuration_entity_state(key, values.get(key))


def control_is_applicable(
    control: ChargingControl,
    values: Mapping[str, ConfigurationValue],
) -> bool:
    """Return whether the charger reports a state in which a control applies."""
    definition = CONTROL_DEFINITIONS[control]

    if definition.working_modes:
        working_mode = _state(values, "G_WorkingMode")
        if working_mode not in definition.working_modes:
            return False

    if definition.charger_modes:
        charger_mode = _state(values, "G_ChargerMode")
        if charger_mode not in definition.charger_modes:
            return False

    if definition.solar_modes:
        solar_mode = _state(values, "G_SolarMode")
        if solar_mode not in definition.solar_modes:
            return False

    return True


def encode_control_value(control: ChargingControl, value: object) -> str:
    """Encode one verified logical control value for ChangeConfiguration."""
    if CONTROL_DEFINITIONS[control].capability != ControlCapability.WRITABLE:
        raise ValueError(f"{control.value} is not a directly writable control")

    if control == ChargingControl.SOLAR_MODE:
        encoded = {
            "disabled": "1&0",
            "pv_linkage": "1&1",
            "pv_linkage_plus": "1&2",
        }.get(str(value))
        if encoded is None:
            raise ValueError(f"Unsupported solar mode: {value}")
        return encoded

    if control == ChargingControl.SOLAR_GRID_IMPORT_LIMIT:
        numeric = float(value)
        if numeric < 0:
            raise ValueError("Solar grid import limit must not be negative")
        return f"{numeric:.2f}".rstrip("0").rstrip(".")

    if control == ChargingControl.OFF_PEAK_ENABLE:
        return "1&Enable" if bool(value) else "1&Disable"

    if control == ChargingControl.WARM_UP:
        return "Enable" if bool(value) else "Disable"

    raise ValueError(f"No encoder is defined for {control.value}")
