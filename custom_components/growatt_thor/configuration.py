"""Structured metadata and values for OCPP configuration keys."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final, TypeAlias


ConfigurationScalar: TypeAlias = str | int | float | bool | None


class ConfigurationDataType(str, Enum):
    """Supported normalized configuration value types."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"


class ConfigurationSensitivity(str, Enum):
    """Sensitivity used when configuration values leave memory."""

    PUBLIC = "public"
    PRIVATE = "private"
    SECRET = "secret"
    UNKNOWN = "unknown"


class ConfigurationRequestGroup(str, Enum):
    """GetConfiguration request group."""

    OPERATIONAL = "operational"
    INFORMATIONAL = "informational"


@dataclass(frozen=True, slots=True)
class ConfigurationDefinition:
    """Metadata for one known OCPP or Growatt configuration key."""

    description: str
    data_type: ConfigurationDataType = ConfigurationDataType.STRING
    unit: str | None = None
    enum_values: tuple[tuple[str, str], ...] = ()
    writable: bool = False
    sensitivity: ConfigurationSensitivity = ConfigurationSensitivity.PUBLIC
    request_group: ConfigurationRequestGroup | None = None

    def enum_label(self, raw_value: str | None) -> str | None:
        """Return the known label for an enum value."""
        if raw_value is None:
            return None
        return next(
            (label for value, label in self.enum_values if value == raw_value),
            None,
        )


@dataclass(frozen=True, slots=True)
class ConfigurationValue:
    """One configuration value returned by the charger."""

    key: str
    raw_value: str | None
    parsed_value: ConfigurationScalar
    readonly: bool | None
    known: bool

    @property
    def definition(self) -> ConfigurationDefinition | None:
        """Return registry metadata when the key is known."""
        return CONFIGURATION_REGISTRY.get(self.key)

    @property
    def enum_label(self) -> str | None:
        """Return a human-readable enum label when one is known."""
        if self.definition is None:
            return None
        return self.definition.enum_label(self.raw_value)

    def as_dict(self, *, redact: bool = False) -> dict[str, object]:
        """Return a serializable representation for future diagnostics use."""
        definition = self.definition
        sensitive = definition is None or definition.sensitivity != ConfigurationSensitivity.PUBLIC
        value: object = "<redacted>" if redact and sensitive else self.parsed_value
        raw_value: object = "<redacted>" if redact and sensitive else self.raw_value

        return {
            "key": self.key,
            "value": value,
            "raw_value": raw_value,
            "readonly": self.readonly,
            "known": self.known,
            "type": definition.data_type.value if definition else ConfigurationDataType.STRING.value,
            "unit": definition.unit if definition else None,
            "enum_label": self.enum_label,
            "writable": definition.writable if definition else False,
            "sensitivity": (
                definition.sensitivity.value
                if definition
                else ConfigurationSensitivity.UNKNOWN.value
            ),
            "description": definition.description if definition else None,
        }


def _definition(
    description: str,
    *,
    data_type: ConfigurationDataType = ConfigurationDataType.STRING,
    unit: str | None = None,
    enum_values: tuple[tuple[str, str], ...] = (),
    writable: bool = False,
    sensitivity: ConfigurationSensitivity = ConfigurationSensitivity.PUBLIC,
    request_group: ConfigurationRequestGroup | None = None,
) -> ConfigurationDefinition:
    return ConfigurationDefinition(
        description=description,
        data_type=data_type,
        unit=unit,
        enum_values=enum_values,
        writable=writable,
        sensitivity=sensitivity,
        request_group=request_group,
    )


_OPERATIONAL = ConfigurationRequestGroup.OPERATIONAL
_INFORMATIONAL = ConfigurationRequestGroup.INFORMATIONAL
_PRIVATE = ConfigurationSensitivity.PRIVATE
_SECRET = ConfigurationSensitivity.SECRET


CONFIGURATION_REGISTRY: Final[Mapping[str, ConfigurationDefinition]] = MappingProxyType(
    {
        # Operational keys used by entities or OCPP diagnostics.
        "G_MaxCurrent": _definition(
            "Maximum charging current per phase",
            data_type=ConfigurationDataType.FLOAT,
            unit="A",
            writable=True,
            request_group=_OPERATIONAL,
        ),
        "G_ExternalLimitPower": _definition(
            "External grid power limit",
            data_type=ConfigurationDataType.FLOAT,
            unit="kW",
            writable=True,
            request_group=_OPERATIONAL,
        ),
        "G_ExternalLimitPowerEnable": _definition(
            "External power limiting enabled",
            data_type=ConfigurationDataType.BOOLEAN,
            writable=True,
            request_group=_OPERATIONAL,
        ),
        "G_ChargerMode": _definition(
            "Charger authorization mode",
            data_type=ConfigurationDataType.INTEGER,
            enum_values=(("1", "HA/RFID"), ("2", "RFID Only"), ("3", "Plug & Charge")),
            writable=True,
            request_group=_OPERATIONAL,
        ),
        "G_ServerURL": _definition(
            "OCPP central-system endpoint",
            sensitivity=_PRIVATE,
            request_group=_OPERATIONAL,
        ),
        "G_AutoChargeTime": _definition(
            "Automatic charging time window",
            writable=True,
            request_group=_OPERATIONAL,
        ),
        "G_LCDCloseEnable": _definition(
            "LCD automatic close setting",
            enum_values=(("Disable", "On"), ("Enable", "Off")),
            writable=True,
            request_group=_OPERATIONAL,
        ),
        "HeartbeatInterval": _definition(
            "OCPP heartbeat interval",
            data_type=ConfigurationDataType.INTEGER,
            unit="s",
            request_group=_OPERATIONAL,
        ),
        "MeterValueSampleInterval": _definition(
            "OCPP periodic meter sample interval",
            data_type=ConfigurationDataType.INTEGER,
            unit="s",
            request_group=_OPERATIONAL,
        ),
        "MeterValuesSampledData": _definition(
            "OCPP measurands included in periodic meter values",
            request_group=_OPERATIONAL,
        ),
        "UnlockConnectorOnEVSideDisconnect": _definition(
            "Unlock connector when the EV disconnects",
            data_type=ConfigurationDataType.BOOLEAN,
            request_group=_OPERATIONAL,
        ),
        "ElectricityMeterOnline": _definition(
            "Electricity meter online state",
            data_type=ConfigurationDataType.BOOLEAN,
            request_group=_OPERATIONAL,
        ),
        "G_WebSocketPingInterval": _definition(
            "Growatt WebSocket ping interval",
            data_type=ConfigurationDataType.INTEGER,
            unit="s",
            request_group=_OPERATIONAL,
        ),
        "G_TimeSharingPrice": _definition(
            "Vendor-encoded time-sharing electricity price",
            writable=True,
            request_group=_OPERATIONAL,
        ),

        # Informational keys. The THOR firmware accepts at most 30 per request.
        "G_ChargerID": _definition(
            "Charger identifier",
            sensitivity=_PRIVATE,
            request_group=_INFORMATIONAL,
        ),
        "G_ChargerRate": _definition(
            "Charger tariff or rate",
            data_type=ConfigurationDataType.FLOAT,
            request_group=_INFORMATIONAL,
        ),
        "G_ChargerLanguage": _definition(
            "Charger display language",
            request_group=_INFORMATIONAL,
        ),
        "G_ChargerNetIP": _definition(
            "Charger network address",
            sensitivity=_PRIVATE,
            request_group=_INFORMATIONAL,
        ),
        "G_ChargerNetDNS": _definition(
            "Charger DNS server",
            sensitivity=_PRIVATE,
            request_group=_INFORMATIONAL,
        ),
        "G_ChargerNetMask": _definition(
            "Charger network mask",
            sensitivity=_PRIVATE,
            request_group=_INFORMATIONAL,
        ),
        "G_ChargerNetMac": _definition(
            "Charger MAC address",
            sensitivity=_PRIVATE,
            request_group=_INFORMATIONAL,
        ),
        "G_ChargerNetGateway": _definition(
            "Charger network gateway",
            sensitivity=_PRIVATE,
            request_group=_INFORMATIONAL,
        ),
        "G_NetworkMode": _definition(
            "Charger network mode",
            request_group=_INFORMATIONAL,
        ),
        "G_WifiSSID": _definition(
            "Wi-Fi network name",
            sensitivity=_PRIVATE,
            request_group=_INFORMATIONAL,
        ),
        "G_MaxTemperature": _definition(
            "Maximum temperature threshold",
            data_type=ConfigurationDataType.INTEGER,
            unit="°C",
            request_group=_INFORMATIONAL,
        ),
        "G_RCDProtection": _definition(
            "RCD protection mode",
            data_type=ConfigurationDataType.INTEGER,
            request_group=_INFORMATIONAL,
        ),
        "G_PowerMeterAddr": _definition(
            "External Modbus meter address",
            data_type=ConfigurationDataType.INTEGER,
            request_group=_INFORMATIONAL,
        ),
        "G_PowerMeterType": _definition(
            "External power meter model",
            request_group=_INFORMATIONAL,
        ),
        "G_ExternalSamplingCurWring": _definition(
            "External meter wiring or sampling mode",
            data_type=ConfigurationDataType.INTEGER,
            request_group=_INFORMATIONAL,
        ),
        "G_TimeZone": _definition(
            "Charger time zone",
            request_group=_INFORMATIONAL,
        ),
        "G_DaylightSavingTime": _definition(
            "Vendor-encoded daylight-saving configuration",
            request_group=_INFORMATIONAL,
        ),
        "G_SolarMode": _definition(
            "Vendor-encoded solar charging mode",
            request_group=_INFORMATIONAL,
        ),
        "G_SolarLimitPower": _definition(
            "Solar power threshold or limit",
            data_type=ConfigurationDataType.FLOAT,
            request_group=_INFORMATIONAL,
        ),
        "G_SolarBoost": _definition(
            "Vendor-encoded solar boost setting",
            request_group=_INFORMATIONAL,
        ),
        "G_SolarThresholdCurr": _definition(
            "Solar current threshold",
            data_type=ConfigurationDataType.FLOAT,
            request_group=_INFORMATIONAL,
        ),
        "G_PeakValleyEnable": _definition(
            "Peak or valley tariff enabled",
            data_type=ConfigurationDataType.BOOLEAN,
            request_group=_INFORMATIONAL,
        ),
        "G_OffPeakTime": _definition(
            "Vendor-encoded off-peak time window",
            request_group=_INFORMATIONAL,
        ),
        "G_OffPeakEnable": _definition(
            "Vendor-encoded off-peak enable setting",
            request_group=_INFORMATIONAL,
        ),
        "G_OffPeakCurr": _definition(
            "Off-peak current setting",
            request_group=_INFORMATIONAL,
        ),
        "G_MeterValueInterval": _definition(
            "Growatt meter-value interval",
            data_type=ConfigurationDataType.INTEGER,
            unit="s",
            request_group=_INFORMATIONAL,
        ),
        "G_WorkingMode": _definition(
            "Charger working mode",
            request_group=_INFORMATIONAL,
        ),
        "G_LowPowerReserveEnable": _definition(
            "Low-power reserve setting",
            request_group=_INFORMATIONAL,
        ),
        "G_FullContinueChargeEnable": _definition(
            "Continue charging after reaching full state",
            request_group=_INFORMATIONAL,
        ),
        "G_RandDelayChargeTime": _definition(
            "Randomized charging delay",
            data_type=ConfigurationDataType.INTEGER,
            request_group=_INFORMATIONAL,
        ),

        # Observed but intentionally not requested or not accepted by tested firmware.
        "AllowOfflineTxForUnknownId": _definition(
            "Allow offline transactions for unknown identifiers",
            data_type=ConfigurationDataType.BOOLEAN,
        ),
        "AuthorizationCacheEnabled": _definition(
            "OCPP authorization cache enabled",
            data_type=ConfigurationDataType.BOOLEAN,
        ),
        "AuthorizeRemoteTxRequests": _definition(
            "Require authorization for remote transaction requests",
            data_type=ConfigurationDataType.BOOLEAN,
        ),
        "ClockAlignedDataInterval": _definition(
            "Clock-aligned meter-data interval",
            data_type=ConfigurationDataType.INTEGER,
            unit="s",
        ),
        "ConnectionTimeOut": _definition(
            "Connector timeout",
            data_type=ConfigurationDataType.INTEGER,
            unit="s",
        ),
        "LocalAuthListEnabled": _definition(
            "Local authorization list enabled",
            data_type=ConfigurationDataType.BOOLEAN,
        ),
        "LocalAuthorizeOffline": _definition(
            "Local authorization while offline",
            data_type=ConfigurationDataType.BOOLEAN,
        ),
        "LocalPreAuthorize": _definition(
            "Local preauthorization enabled",
            data_type=ConfigurationDataType.BOOLEAN,
        ),
        "WebSocketPingInterval": _definition(
            "OCPP WebSocket ping interval",
            data_type=ConfigurationDataType.INTEGER,
            unit="s",
        ),
        "G_4GAPN": _definition("Cellular APN"),
        "G_4GPassword": _definition("Cellular password", sensitivity=_SECRET),
        "G_4GUserName": _definition("Cellular username", sensitivity=_PRIVATE),
        "G_Authentication": _definition(
            "Growatt local authentication value",
            sensitivity=_SECRET,
        ),
        "G_CardPin": _definition("Local card or PIN value", sensitivity=_SECRET),
        "G_PeriodTime": _definition("Vendor-encoded period definition"),
        "G_WifiPassword": _definition("Wi-Fi password", sensitivity=_SECRET),
        "G_RFEnable": _definition("Unconfirmed Growatt RF setting"),
        "LightIntensity": _definition("Unconfirmed light intensity setting"),
    }
)


OPERATIONAL_CONFIGURATION_KEYS: Final[tuple[str, ...]] = tuple(
    key
    for key, definition in CONFIGURATION_REGISTRY.items()
    if definition.request_group == ConfigurationRequestGroup.OPERATIONAL
)
INFORMATIONAL_CONFIGURATION_KEYS: Final[tuple[str, ...]] = tuple(
    key
    for key, definition in CONFIGURATION_REGISTRY.items()
    if definition.request_group == ConfigurationRequestGroup.INFORMATIONAL
)


CONFIGURATION_ENTITY_OPTIONS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "G_WorkingMode": ("fast", "pv_linkage", "off_peak"),
        "G_ChargerMode": (
            "home_assistant_rfid",
            "rfid_only",
            "plug_and_charge",
        ),
        "G_ExternalSamplingCurWring": (
            "none",
            "ct_2000_1",
            "power_meter",
            "ct_3000_1",
        ),
    }
)

_CONFIGURATION_ENTITY_ALIASES: Final[Mapping[str, Mapping[str, str]]] = (
    MappingProxyType(
        {
            "G_WorkingMode": MappingProxyType(
                {
                    "fast": "fast",
                    "fastmode": "fast",
                    "pvlink": "pv_linkage",
                    "pvlinkage": "pv_linkage",
                    "offpeak": "off_peak",
                    "offpeakmode": "off_peak",
                }
            ),
            "G_ChargerMode": MappingProxyType(
                {
                    "1": "home_assistant_rfid",
                    "2": "rfid_only",
                    "3": "plug_and_charge",
                }
            ),
            "G_ExternalSamplingCurWring": MappingProxyType(
                {
                    "0": "none",
                    "1": "ct_2000_1",
                    "2": "power_meter",
                    "3": "ct_3000_1",
                }
            ),
        }
    )
)


def configuration_entity_state(
    key: str,
    value: ConfigurationValue | None,
) -> ConfigurationScalar:
    """Return a stable Home Assistant state for a retained configuration value."""
    if value is None or value.raw_value is None or not value.raw_value.strip():
        return None

    aliases = _CONFIGURATION_ENTITY_ALIASES.get(key)
    if aliases is None:
        return value.parsed_value

    normalized = "".join(
        character
        for character in value.raw_value.casefold()
        if character.isalnum()
    )
    return aliases.get(normalized)


def _parse_value(
    definition: ConfigurationDefinition | None,
    raw_value: str | None,
) -> ConfigurationScalar:
    if raw_value is None or definition is None:
        return raw_value

    try:
        if definition.data_type == ConfigurationDataType.INTEGER:
            return int(raw_value)
        if definition.data_type == ConfigurationDataType.FLOAT:
            return float(raw_value)
        if definition.data_type == ConfigurationDataType.BOOLEAN:
            normalized = raw_value.strip().lower()
            if normalized in {"1", "true", "enable", "enabled", "on"}:
                return True
            if normalized in {"0", "false", "disable", "disabled", "off"}:
                return False
    except (TypeError, ValueError):
        pass

    return raw_value


def configuration_value_from_item(
    item: Mapping[str, object],
) -> ConfigurationValue | None:
    """Convert one OCPP configuration item without losing its raw value."""
    key = item.get("key")
    if not isinstance(key, str) or not key:
        return None

    raw = item.get("value")
    raw_value = None if raw is None else str(raw)
    readonly_raw = item.get("readonly")
    readonly = readonly_raw if isinstance(readonly_raw, bool) else None
    definition = CONFIGURATION_REGISTRY.get(key)

    return ConfigurationValue(
        key=key,
        raw_value=raw_value,
        parsed_value=_parse_value(definition, raw_value),
        readonly=readonly,
        known=definition is not None,
    )


def merge_configuration_values(
    current: Mapping[str, ConfigurationValue],
    items: Iterable[Mapping[str, object]],
) -> tuple[dict[str, ConfigurationValue], bool]:
    """Merge returned values into the last-known configuration snapshot."""
    merged = dict(current)
    changed = False

    for item in items:
        value = configuration_value_from_item(item)
        if value is None:
            continue
        if merged.get(value.key) != value:
            merged[value.key] = value
            changed = True

    return merged, changed


def normalize_unknown_configuration_keys(keys: Iterable[object]) -> tuple[str, ...]:
    """Return stable, unique unknown-key names from an OCPP response."""
    return tuple(sorted({str(key) for key in keys if key is not None and str(key)}))


def serialize_configuration_values(
    values: Mapping[str, ConfigurationValue],
    *,
    redact: bool = True,
) -> dict[str, dict[str, object]]:
    """Return a stable, serializable configuration snapshot."""
    return {
        key: values[key].as_dict(redact=redact)
        for key in sorted(values)
    }


def redact_configuration_value(key: object, value: object) -> object:
    """Redact non-public values before logging or diagnostics."""
    definition = CONFIGURATION_REGISTRY.get(str(key))
    if definition is None or definition.sensitivity != ConfigurationSensitivity.PUBLIC:
        return "<redacted>"
    return value
