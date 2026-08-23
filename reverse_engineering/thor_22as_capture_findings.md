# Additional THOR 22AS Capture Findings

This addendum complements the original reverse-engineering notes in
[`README.md`](README.md) with observations from another Growatt owner and
another capture set. It keeps wire evidence separate from interpretation and
current integration behavior.

## Scope and evidence

The observations below were validated with redacted traces from:

| Device | Firmware | Protocol |
|---|---|---|
| Growatt THOR 22AS | `THOR_22AS-V2.2.16-20240902` | OCPP 1.6J over WebSocket |

The original cloud connection used:

- WebSocket subprotocol `ocpp1.6`
- endpoint `ws://evcharge.growatt.com:80/ocpp/ws/<CHARGER_ID>`
- HTTP Basic Authentication during the WebSocket upgrade

Evidence labels used in this document:

| Label | Meaning |
|---|---|
| `observed` | Seen on the wire with the firmware above |
| `inferred` | Interpretation derived from naming, value shape, or behavior; more captures are needed |
| `implemented` | Handled or exposed by the current Home Assistant integration |
| `unknown` | Returned by the charger in `GetConfiguration.conf.unknownKey` |

A row can have multiple labels. `observed` confirms the field and its raw
value, not every interpretation of that value.

## Safety and redaction

OCPP traffic from this charger is unencrypted and captures can contain
credentials and personally identifying data. Before sharing a trace, remove:

- HTTP `Authorization` headers
- `G_WifiPassword`, `G_4GPassword`, `G_Authentication`, and `G_CardPin`
- RFID or other ID tags
- charger serial numbers, local IP addresses, MAC addresses, and exact location

The integration intentionally does not request `G_WifiPassword`.

## OCPP message map

`CP` means charge point and `CS` means the OCPP central system implemented by
Home Assistant.

| OCPP message / vendor message | Direction | Observed example or purpose | Current Home Assistant mapping | Firmware | Status |
|---|---|---|---|---|---|
| `BootNotification` | CP -> CS | `chargePointVendor=Growatt`, `chargePointModel=THOR_22AS`, serial and firmware | Payload is logged; connection creates the Charge Point ID sensor | 2.2.16 | observed, implemented |
| `Heartbeat` | CP -> CS | Periodic clock synchronization; Central System requests a 60-second interval in `BootNotification.conf` | Returns current UTC time and refreshes connection liveness; any inbound OCPP message also counts as activity | 2.2.16 | observed, implemented |
| `StatusNotification` | CP -> CS | `Preparing`, `Charging`, `Finishing`; `errorCode=NoError` and an empty `info` field | Status sensor; other diagnostic fields are not retained yet | 2.2.16 | observed, implemented |
| `StartTransaction` | CP -> CS | Starts an OCPP transaction | Resets live session values and returns a CS-generated transaction ID | 2.2.16 | implemented |
| `MeterValues` | CP -> CS | Charging energy, current, voltage, power, and temperature | Live charging and per-phase sensors | 2.2.16 | observed, implemented |
| `StopTransaction` | CP -> CS | Ends a transaction with meter stop and reason | Clears active transaction state | 2.2.16 | observed, implemented |
| `TriggerMessage` | CS -> CP | Captured requests for `BootNotification` and `StatusNotification` | Integration requests status during manual refresh | 2.2.16 | observed, implemented |
| `GetConfiguration` | CS -> CP | Reads standard OCPP and Growatt `G_*` keys | Known operational values are mapped; informational values are currently logged | 2.2.16 | observed, implemented |
| `ChangeConfiguration` | CS -> CP | Writes one configuration value | Used by numbers, switches, time entities, and charger mode | 2.2.16 | observed, implemented |
| `DataTransfer/get_external_meterval` | CS -> CP | Requests the external power meter snapshot | Grid power, voltage, and current sensors | 2.2.16 | observed, implemented |
| `DataTransfer/currentrecord` | CP -> CS | Current or latest Growatt session record | Last-session sensors and CSV logging | 2.2.16 | observed, implemented |
| `DataTransfer/frozenrecord` | CP -> CS | Completed Growatt session record | Last-session sensors and CSV logging | 2.2.16 | implemented |
| `DataTransfer/appconfigmode` | CS -> CP | Enables charger AP mode | Options flow with confirmation | 2.2.16 | implemented |
| `RemoteStartTransaction` | CS -> CP | Requests a new charging session | Start charging button | 2.2.16 | implemented |
| `RemoteStopTransaction` | CS -> CP | Requests the active transaction to stop | Stop charging button | 2.2.16 | observed, implemented |

Typical connection flow:

```text
BootNotification -> StatusNotification -> Heartbeat -> ...
```

One supported charging flow is:

```text
RemoteStartTransaction -> StartTransaction -> StatusNotification(Charging)
-> MeterValues* -> RemoteStopTransaction/other stop -> StopTransaction
-> StatusNotification
```

### Transaction ID ownership

The central system assigns the OCPP `transactionId` in
`StartTransaction.conf`. The charger then reuses that ID in `MeterValues`,
`StopTransaction`, and Growatt session records. It is not assigned by the
charger.

## MeterValues

Although an observed configuration contained
`MeterValuesSampledData=Energy.Active.Import.Register`, the charger sent
additional measurands during an active session.

| Measurand | Unit | Phase | Context observed | Current Home Assistant mapping | Firmware | Status |
|---|---|---|---|---|---|---|
| `Energy.Active.Import.Register` | `Wh` | none | `Sample.Clock`, `Sample.Periodic` | Energy Charged, converted to kWh | 2.2.16 | observed, implemented |
| `Current.Import` | `A` | L1, L2, L3 | periodic samples | Current L1/L2/L3 | 2.2.16 | observed, implemented |
| `Voltage` | `V` | L1, L2, L3 | periodic samples | Voltage L1/L2/L3 | 2.2.16 | observed, implemented |
| `Power.Active.Import` | `W` | L1, L2, L3 | periodic samples | Power L1/L2/L3 and summed Charging Power | 2.2.16 | observed, implemented |
| `Temperature` | `Celsius` | none | periodic samples | Temperature | 2.2.16 | observed, implemented |

One capture represented a two-phase session: L1 and L2 carried current while
L3 remained at zero. Unknown measurands are currently not retained by the
coordinator.

## Growatt DataTransfer payloads

Growatt encodes these payloads as query-string-like data. The raw value should
be preserved because unknown fields may be added by other firmware versions.

### `get_external_meterval`

The integration sends:

```text
DataTransfer(vendorId="Growatt", messageId="get_external_meterval")
```

The request is sent after connecting and periodically in every working mode.
The external meter supplies both load-balancing and PV-Linkage measurements;
`G_ExternalLimitPowerEnable=0` therefore does not disable this polling.

An observed response payload was:

```text
used=1&wring=1&u-voltage=234&v-voltage=233&w-voltage=233&u-current=5&v-current=4&w-current=4&power=-3446
```

Cloud-originated requests in the traces sometimes omitted `vendorId`; the
integration sends `vendorId=Growatt` and the tested charger accepts it.

| Field | Interpretation | Current Home Assistant mapping | Firmware | Status |
|---|---|---|---|---|
| `used` | Usage/availability flag; exact semantics not confirmed | `meter_used` sensor attribute | 2.2.16 | observed, inferred, implemented |
| `wring` | Vendor spelling; likely describes the active phase wiring | `wiring` sensor attribute | 2.2.16 | observed, inferred, implemented |
| `u-voltage` | L1 voltage in V | Grid voltage L1 | 2.2.16 | observed, implemented |
| `v-voltage` | L2 voltage in V | Grid voltage L2 | 2.2.16 | observed, implemented |
| `w-voltage` | L3 voltage in V | Grid voltage L3 | 2.2.16 | observed, implemented |
| `u-current` | L1 current in A | Grid current L1 | 2.2.16 | observed, implemented |
| `v-current` | L2 current in A | Grid current L2 | 2.2.16 | observed, implemented |
| `w-current` | L3 current in A | Grid current L3 | 2.2.16 | observed, implemented |
| `power` | Signed total grid power in W; import/export sign needs more captures | Grid power | 2.2.16 | observed, inferred, implemented |

Do not treat the sign of `power` as a proven import/export convention yet.

### `currentrecord` and `frozenrecord`

Observed `currentrecord` example:

```text
id=346&connectorId=1&chargemode=3&plugtime=2025-08-24 11:47:21&unplugtime=2025-08-25 10:04:23&starttime=2025-08-25 09:56:06&endtime=2025-08-25 10:04:23&costenergy=211&costmoney=4&transactionId=1622129&workmode=3
```

| Field | Interpretation | Current Home Assistant mapping | Firmware | Status |
|---|---|---|---|---|
| `id` | Growatt record identifier | Not exposed | 2.2.16 | observed |
| `connectorId` | OCPP connector number | Parsed but not retained | 2.2.16 | observed |
| `chargemode` | Growatt charging mode code | Last Session Charge Mode | 2.2.16 | observed, implemented |
| `plugtime` | Cable connected time | Last Session Plug Time | 2.2.16 | observed, implemented |
| `unplugtime` | Cable disconnected time | Last Session Unplug Time | 2.2.16 | observed, implemented |
| `starttime` | Charging start time | Last Session Start | 2.2.16 | observed, implemented |
| `endtime` | Charging end time | Last Session End | 2.2.16 | observed, implemented |
| `costenergy` | Energy in Wh; integration divides by 1000 for kWh | Last Session Energy and CSV | 2.2.16 | observed, inferred, implemented |
| `costmoney` | Currency minor unit; integration divides by 100 | Last Session Cost and CSV | 2.2.16 | observed, inferred, implemented |
| `transactionId` | OCPP transaction ID assigned by the central system | Last Session Transaction ID and CSV | 2.2.16 | observed, implemented |
| `workmode` | Growatt work mode code | Last Session Work Mode | 2.2.16 | observed, implemented |

The current integration uses the same session parser for `currentrecord` and
`frozenrecord`.

### Negative result: `getChargerConfigInfo`

`DataTransfer` calls with `messageId=getChargerConfigInfo` and vendor IDs
`Growatt`, `GROWATT`, and `ATESS` all returned `UnknownMessageId` on the tested
firmware. This API/app concept is therefore not a confirmed charger
`DataTransfer` message.

## Configuration reference

All rows marked `observed` below were returned by `GetConfiguration` on the
tested firmware. Direction is CP -> CS in the response. A `readonly=false`
value in one capture is not sufficient evidence that changing the key is safe;
writable controls require separate before/after captures.

### Standard and OCPP-related keys

| Key | Example | Meaning | Current Home Assistant mapping | Firmware | Status |
|---|---|---|---|---|---|
| `AllowOfflineTxForUnknownId` | `false` | Allow offline transactions for unknown ID tags | Not requested | 2.2.16 | observed |
| `AuthorizationCacheEnabled` | `false` | OCPP authorization cache | Not requested | 2.2.16 | observed |
| `AuthorizeRemoteTxRequests` | `false` | Require authorization for remote starts | Not requested | 2.2.16 | observed |
| `ConnectionTimeOut` | `90` | Connector timeout in seconds | Not requested | 2.2.16 | observed |
| `HeartbeatInterval` | `60` | Heartbeat interval in seconds | Preserved in diagnostics | 2.2.16 | observed, implemented |
| `LocalAuthListEnabled` | `false` | Local authorization list | Not requested | 2.2.16 | observed |
| `LocalAuthorizeOffline` | `false` | Local authorization while offline | Not requested | 2.2.16 | observed |
| `LocalPreAuthorize` | `false` | Local preauthorization | Not requested | 2.2.16 | observed |
| `MeterValueSampleInterval` | `5` | Periodic meter sample interval in seconds | Preserved in diagnostics | 2.2.16 | observed, implemented |
| `MeterValuesSampledData` | `Energy.Active.Import.Register` | Requested periodic measurands | Preserved in diagnostics | 2.2.16 | observed, implemented |
| `UnlockConnectorOnEVSideDisconnect` | `true` | Unlock when the EV disconnects | Preserved in diagnostics | 2.2.16 | observed, implemented |
| `WebSocketPingInterval` | `30` | WebSocket ping interval in seconds | Not requested; Growatt-prefixed variant is queried | 2.2.16 | observed |

### Growatt keys

| Key | Redacted/observed example | Meaning | Current Home Assistant mapping | Firmware | Status |
|---|---|---|---|---|---|
| `G_4GAPN` | `Default` | Cellular APN | Not requested | 2.2.16 | observed |
| `G_4GPassword` | `<redacted>` | Cellular password | Not requested; sensitive | 2.2.16 | observed |
| `G_4GUserName` | `<redacted>` | Cellular username | Not requested; sensitive | 2.2.16 | observed |
| `G_Authentication` | `<redacted>` | Growatt local authentication value; exact role not confirmed | Not requested; sensitive | 2.2.16 | observed, inferred |
| `G_AutoChargeTime` | `00:00-00:00` | Automatic charging time window | Auto Charge Start/Stop Time entities | 2.2.16 | observed, implemented |
| `G_CardPin` | `<redacted>` | Local card/PIN value | Not requested; sensitive | 2.2.16 | observed, inferred |
| `G_ChargerID` | `<redacted>` | Charger identifier | Preserved in diagnostics; Charge Point ID comes from the OCPP connection | 2.2.16 | observed, implemented |
| `G_ChargerLanguage` | `English` | Charger display language | Preserved in diagnostics | 2.2.16 | observed, implemented |
| `G_ChargerMode` | `3` | `1=HA/RFID` (`APP` in the charger web page), `2=RFID Only`, `3=Plug & Charge` | Charger mode in options flow and read-only authorization-mode sensor | 2.2.16 | observed, implemented |
| `G_ChargerNetDNS` | `<redacted>` | Charger DNS server | Preserved in diagnostics; privacy-sensitive | 2.2.16 | observed, implemented |
| `G_ChargerNetGateway` | `<redacted>` | Charger network gateway | Preserved in diagnostics; privacy-sensitive | 2.2.16 | observed, implemented |
| `G_ChargerNetIP` | `<redacted>` | Charger network address | Preserved in diagnostics; privacy-sensitive | 2.2.16 | observed, implemented |
| `G_ChargerNetMac` | `<redacted>` | Charger MAC address | Preserved in diagnostics; privacy-sensitive | 2.2.16 | observed, implemented |
| `G_ChargerNetMask` | `<redacted>` | Charger network mask | Preserved in diagnostics; privacy-sensitive | 2.2.16 | observed, implemented |
| `G_ChargerRate` | `0.23` | Charger tariff/rate; relationship to time-sharing price needs confirmation | Preserved in diagnostics | 2.2.16 | observed, inferred, implemented |
| `G_DaylightSavingTime` | `00-00&00-00` | Daylight-saving configuration; value format not confirmed | Preserved in diagnostics | 2.2.16 | observed, inferred, implemented |
| `G_ExternalLimitPower` | `45` | External grid power limit in kW in the tested setup | Loadbalancing limit number | 2.2.16 | observed, implemented |
| `G_ExternalLimitPowerEnable` | `0` | Enable external power limiting | Loadbalancing switch | 2.2.16 | observed, implemented |
| `G_ExternalSamplingCurWring` | `1` | External current sampling: `0=CT 2000:1`, `1=PowerMeter`, `2=CT 3000:1`; these OCPP values differ from the shifted charger web-page dropdown values | Read-only External Sampling Method sensor | 2.2.16 | observed, implemented |
| `G_LowPowerReserveEnable` | `Disable` | Low-power reserve setting | Preserved in diagnostics | 2.2.16 | observed, inferred, implemented |
| `G_MaxCurrent` | `32.00` | Maximum charging current per phase in A | Max Current number | 2.2.16 | observed, implemented |
| `G_MaxTemperature` | `80` | Maximum temperature threshold in Celsius | Preserved in diagnostics | 2.2.16 | observed, inferred, implemented |
| `G_MeterValueInterval` | `5` | Growatt meter-value interval in seconds | Preserved in diagnostics | 2.2.16 | observed, inferred, implemented |
| `G_NetworkMode` | `DHCP` | Charger network mode | Preserved in diagnostics | 2.2.16 | observed, implemented |
| `G_OffPeakCurr` | empty | Off-peak current setting | Preserved in diagnostics | 2.2.16 | observed, inferred, implemented |
| `G_OffPeakEnable` | `1&Disable` | Vendor-encoded off-peak enable setting | Preserved in diagnostics | 2.2.16 | observed, inferred, implemented |
| `G_OffPeakTime` | `00:00-05:00=0&1` | Vendor-encoded off-peak time window | Preserved in diagnostics | 2.2.16 | observed, inferred, implemented |
| `G_PeakValleyEnable` | `0` | Peak/valley tariff enable setting | Preserved in diagnostics | 2.2.16 | observed, inferred, implemented |
| `G_PeriodTime` | `1&time1=00:00-05:00` | Vendor-encoded period definition | Not requested | 2.2.16 | observed, inferred |
| `G_PowerMeterAddr` | `2` | External Modbus meter address | Read-only Power Meter Address sensor | 2.2.16 | observed, implemented |
| `G_PowerMeterType` | `Eastron SDM630` | External meter model/type | Read-only Power Meter Type sensor | 2.2.16 | observed, implemented |
| `G_RCDProtection` | `6` | RCD protection mode; enum not confirmed | Preserved in diagnostics | 2.2.16 | observed, inferred, implemented |
| `G_RandDelayChargeTime` | `0` | Randomized charging delay | Preserved in diagnostics | 2.2.16 | observed, inferred, implemented |
| `G_ServerURL` | `ws://<ha-host>:9000` | OCPP central-system endpoint | Server URL diagnostic sensor | 2.2.16 | observed, implemented |
| `G_SolarBoost` | `1&Disable` | Vendor-encoded solar boost setting | Preserved in diagnostics | 2.2.16 | observed, inferred, implemented |
| `G_SolarLimitPower` | `1.98` | Solar power threshold/limit; exact behavior needs confirmation | Preserved in diagnostics | 2.2.16 | observed, inferred, implemented |
| `G_SolarMode` | `1&1`, `1&2` | Vendor-encoded solar mode | Preserved in diagnostics | 2.2.16 | observed, inferred, implemented |
| `G_SolarThresholdCurr` | `0` | Solar current threshold | Preserved in diagnostics | 2.2.16 | observed, inferred, implemented |
| `G_TimeZone` | `UTC+2` | Charger time zone | Preserved in diagnostics | 2.2.16 | observed, implemented |
| `G_WebSocketPingInterval` | `30` | Growatt WebSocket ping interval in seconds | Preserved in diagnostics | 2.2.16 | observed, implemented |
| `G_WifiPassword` | `<redacted>` | Wi-Fi password | Intentionally not requested; sensitive | 2.2.16 | observed |
| `G_WifiSSID` | `<redacted>` | Wi-Fi network name | Preserved in diagnostics; privacy-sensitive | 2.2.16 | observed, implemented |
| `G_WorkingMode` | `PVlink` | Charger working mode: Fast, PV Linkage, or Off-Peak; separate from `G_ChargerMode` authorization | Read-only Working Mode sensor; last session also exposes a work-mode code | 2.2.16 | observed, implemented |

### Queried or implemented without matching local capture evidence

These keys occur in the current integration but were not present in the local
capture set used for the tables above:

| Key | Current use | Status |
|---|---|---|
| `ElectricityMeterOnline` | Preserved in diagnostics | implemented |
| `G_FullContinueChargeEnable` | Preserved in diagnostics | implemented |
| `G_LCDCloseEnable` | LCD Display switch | implemented |
| `G_TimeSharingPrice` | Electricity price number and sensor | implemented |

### Keys rejected by the tested firmware

| Key | Charger response | Firmware | Status |
|---|---|---|---|
| `G_RFEnable` | Included in `unknownKey` | 2.2.16 | unknown |
| `LightIntensity` | Included in `unknownKey` | 2.2.16 | unknown |
| `G_DRM3Percentage` | Included in `unknownKey` | 2.2.16 | unknown |
| `G_DRM4Percentage` | Included in `unknownKey` | 2.2.16 | unknown |

`G_RFEnable` and `G_PeriodTime` must not be treated alike: `G_RFEnable` was
rejected as unknown, while `G_PeriodTime` returned a value.

## Current implementation boundary

The integration currently exposes only a validated subset of configuration as
Home Assistant controls. Other requested values are logged but not retained in
a generic configuration registry. Unknown meter measurands and unrecognized
DataTransfer fields are also not retained.

This is intentional for controls: a key name is not enough evidence to make a
setting writable. Future controls should be added one use case at a time after
capturing the value before and after the corresponding charger/app change.
