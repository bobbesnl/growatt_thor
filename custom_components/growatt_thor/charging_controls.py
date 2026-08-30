"""Mode-aware capabilities for Growatt charging configuration controls."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final, Mapping

from .configuration import ConfigurationValue, configuration_entity_state


WORKING_MODE_OPTIONS = ("fast", "pv_linkage", "pv_linkage_plus", "off_peak")
PV_LINKAGE_WORKING_MODES = frozenset({"pv_linkage", "pv_linkage_plus"})


class ControlCapability(str, Enum):
    """Describe how safely one setting can be exposed in Home Assistant."""

    WRITABLE = "writable"
    COMPOUND = "compound"
    READ_ONLY = "read_only"


class ControlWritePolicy(str, Enum):
    """Describe when a configuration control may change charger state."""

    ANYTIME = "anytime"
    IDLE_ONLY = "idle_only"


class ChargingControl(str, Enum):
    """Configuration controls whose applicability depends on charger state."""

    LOAD_BALANCING = "load_balancing"
    LOAD_BALANCING_LIMIT = "load_balancing_limit"
    AUTO_CHARGE_SCHEDULE = "auto_charge_schedule"
    WORKING_MODE = "working_mode"
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
    EXTERNAL_SAMPLING_METHOD = "external_sampling_method"
    POWER_METER_TYPE = "power_meter_type"
    POWER_METER_ADDRESS = "power_meter_address"


@dataclass(frozen=True, slots=True)
class ControlDefinition:
    """Describe one control and the configuration states it requires."""

    capability: ControlCapability
    configuration_key: str
    write_policy: ControlWritePolicy = ControlWritePolicy.IDLE_ONLY
    working_modes: frozenset[str] = frozenset()
    charger_modes: frozenset[str] = frozenset()
    solar_modes: frozenset[str] = frozenset()
    external_sampling_methods: frozenset[str] = frozenset()
    check_reported_readonly: bool = True


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
            ChargingControl.WORKING_MODE: ControlDefinition(
                ControlCapability.WRITABLE,
                "G_WorkingMode",
                check_reported_readonly=False,
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
                solar_modes=frozenset({"pv_linkage"}),
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
                ControlCapability.READ_ONLY,
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
            ChargingControl.EXTERNAL_SAMPLING_METHOD: ControlDefinition(
                ControlCapability.WRITABLE,
                "G_ExternalSamplingCurWring",
            ),
            ChargingControl.POWER_METER_TYPE: ControlDefinition(
                ControlCapability.WRITABLE,
                "G_PowerMeterType",
                external_sampling_methods=frozenset({"power_meter"}),
            ),
            ChargingControl.POWER_METER_ADDRESS: ControlDefinition(
                ControlCapability.WRITABLE,
                "G_PowerMeterAddr",
                external_sampling_methods=frozenset({"power_meter"}),
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

    if definition.external_sampling_methods:
        sampling_method = _state(values, "G_ExternalSamplingCurWring")
        if sampling_method not in definition.external_sampling_methods:
            return False

    return True


def control_write_block_reason(
    control: ChargingControl,
    values: Mapping[str, ConfigurationValue],
    *,
    connected: bool,
    transaction_active: bool,
    charger_faulted: bool = False,
) -> str | None:
    """Return why a control cannot currently write, or ``None``."""
    definition = CONTROL_DEFINITIONS[control]

    if definition.capability == ControlCapability.READ_ONLY:
        return "read_only_control"
    if block_reason := charger_write_block_reason(
        connected=connected,
        charger_faulted=charger_faulted,
    ):
        return block_reason
    if (
        definition.write_policy == ControlWritePolicy.IDLE_ONLY
        and transaction_active
    ):
        return "active_transaction"
    if not control_is_applicable(control, values):
        return "control_not_applicable"

    reported = values.get(definition.configuration_key)
    if (
        definition.check_reported_readonly
        and reported is not None
        and reported.readonly is True
    ):
        return "configuration_read_only"

    return None


def charger_write_block_reason(
    *,
    connected: bool,
    charger_faulted: bool,
) -> str | None:
    """Return a connection/status blocker shared by legacy controls."""
    if not connected:
        return "charger_disconnected"
    if charger_faulted:
        return "charger_faulted"
    return None


def transaction_state_is_active(
    *,
    active_transaction: object,
    transaction_id: object,
    status: object,
) -> bool:
    """Combine retained transaction identifiers and OCPP charging states."""
    normalized_status = (
        status.value if hasattr(status, "value") else str(status or "")
    )
    return (
        active_transaction is not None
        or transaction_id is not None
        or normalized_status in {"Charging", "SuspendedEV", "SuspendedEVSE"}
    )


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

    if control == ChargingControl.WARM_UP:
        return "Enable" if bool(value) else "Disable"

    if control == ChargingControl.EXTERNAL_SAMPLING_METHOD:
        encoded = {
            "ct_2000_1": "0",
            "power_meter": "1",
            "ct_3000_1": "2",
        }.get(str(value))
        if encoded is None:
            raise ValueError(f"Unsupported external sampling method: {value}")
        return encoded

    if control == ChargingControl.POWER_METER_TYPE:
        encoded = {
            "none": "0",
            "acrel_dds1352": "1",
            "acrel_dtsd1352_three": "2",
            "eastron_sdm230": "3",
            "eastron_sdm630_three": "4",
            "eastron_sdm120_mid": "5",
            "eastron_sdm72d_mid_three": "6",
            "din_rail_dtsu666_mid_three": "7",
            "chint_dtsu666_mid_three": "10",
            "chint_ddsu666": "11",
        }.get(str(value))
        if encoded is None:
            raise ValueError(f"Unsupported power meter type: {value}")
        return encoded

    if control == ChargingControl.POWER_METER_ADDRESS:
        numeric = float(value)
        if not numeric.is_integer() or not 1 <= numeric <= 247:
            raise ValueError("Power meter address must be an integer from 1 to 247")
        return str(int(numeric))

    raise ValueError(f"No encoder is defined for {control.value}")


def encode_working_mode(option: str) -> tuple[str, str]:
    """Return the captured configuration write used to select a working mode."""
    encoded = {
        "fast": ("G_SolarMode", "1&0"),
        "pv_linkage": ("G_SolarMode", "1&1"),
        "pv_linkage_plus": ("G_SolarMode", "1&2"),
        "off_peak": ("G_OffPeakEnable", "1&Enable"),
    }.get(option)
    if encoded is None:
        raise ValueError(f"Unsupported working mode: {option}")
    return encoded


def selected_working_mode(
    values: Mapping[str, ConfigurationValue],
) -> str | None:
    """Combine effective working mode and PV submode for the HA selector."""
    working_mode = _state(values, "G_WorkingMode")
    if working_mode != "pv_linkage":
        return working_mode if isinstance(working_mode, str) else None

    solar_mode = _state(values, "G_SolarMode")
    if solar_mode == "pv_linkage_plus":
        return "pv_linkage_plus"
    return "pv_linkage"


def available_working_mode_options(
    current_option: str | None,
    *,
    external_meter_ready: bool,
) -> list[str]:
    """Return modes that remain safe to select for the current meter health."""
    if external_meter_ready:
        return list(WORKING_MODE_OPTIONS)
    return [
        option
        for option in WORKING_MODE_OPTIONS
        if option not in PV_LINKAGE_WORKING_MODES or option == current_option
    ]
