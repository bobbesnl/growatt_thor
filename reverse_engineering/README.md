# Growatt THOR -- OCPP Reverse Engineering & Home Assistant Integration

## Overview

This document describes how the Growatt THOR EV charger was reverse
engineered, how traffic was captured and analyzed, and how a Home
Assistant--based OCPP server can fully replace the Growatt Cloud.

The focus is **OCPP 1.6 over WebSocket**, with Growatt-specific vendor
extensions.

------------------------------------------------------------------------

## Architecture Summary

    Growatt THOR  →  Home Assistant OCPP Server
                        |
                        +-- Coordinator
                        +-- Sensors
                        +-- Services

Key principle: \> **The THOR only sends live data after specific vendor
triggers.**

------------------------------------------------------------------------

## Network Capture Setup

### 1. socat (TCP proxy)

Used to transparently proxy traffic between the THOR and the Growatt
server (or Home Assistant OCPP server).

Example systemd service:

``` ini
[Unit]
Description=THOR OCPP socat proxy (observer mode)
After=network.target

[Service]
ExecStart=/usr/bin/socat -d -d \
  TCP-LISTEN:9000,fork,reuseaddr,keepalive \
  TCP:evcharge.growatt.com:80
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Purpose: - MITM inspection - No firmware changes required - Safe and
reversible

------------------------------------------------------------------------

### 2. tcpdump capture

Used to record raw traffic for offline analysis.

Example systemd service:

``` ini
[Unit]
Description=THOR OCPP raw traffic logger (pcap)
After=network.target thor-ocpp-socat.service
Requires=thor-ocpp-socat.service

[Service]
ExecStartPre=/bin/mkdir -p /var/log/thor-ocpp/raw
ExecStartPre=/bin/chown root:root /var/log/thor-ocpp/raw
ExecStartPre=/bin/chmod 755 /var/log/thor-ocpp/raw
ExecStart=/usr/bin/tcpdump \
  -i any \
  -s 0 \
  -w /var/log/thor-ocpp/raw/ocpp-%%Y-%%m-%%d.pcap \
  -G 86400 \
  -W 7 \
  tcp port 9000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

------------------------------------------------------------------------

## PCAP Analysis

### Key Findings

  Observation                       Meaning
  --------------------------------- ---------------------------
  WebSocket Binary frames           OCPP JSON inside
  No MeterValues pushed             Expected Growatt behavior
  Data appears after DataTransfer   Vendor trigger required

------------------------------------------------------------------------

## tshark Limitations

`tshark` often fails to decode WebSocket payloads correctly due to: -
fragmentation - masking - binary opcode usage

Solution: - Extract TCP payloads - Decode manually in Python

------------------------------------------------------------------------

## Python OCPP Extraction

A custom script was used to: - parse TCP payloads - extract JSON arrays
(`[2, ...]`, `[3, ...]`) - classify OCPP CALL / CALLRESULT

This enabled identification of: - `get_external_meterval` -
`frozenrecord` - `GetConfiguration`

------------------------------------------------------------------------

## Found parameters

🔌 Charging Behavior
| Parameter                         | Example Value(s) | Min  | Max  | Description                                                                                                                                          |
| --------------------------------- | ---------------- | ---- | ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| GMaxCurrent                       | 15, 16           | 6 A  | 32 A | Maximum charging current in amperes per phase. Primary setting for charging speed.                                     |
| GChargerMode                      | 1, 2, 3          | 1    | 3    | Operating mode: 1 = HA/RFID (combined), 2 = RFID Only, 3 = Plug & Charge (no authorization required).  ​                 |
| GWorkingMode                      | —                | —    | —    | Overall working mode of the charger (solar, normal, etc.).  ​                                                            |
| GAutoChargeTime                   | 2301-0559        | 0000 | 2359 | Time window for automatic charging in format HHmm-HHmm. The charger will not start automatically outside this window.  ​ |
| UnlockConnectorOnEVSideDisconnect | true, false      | —    | —    | Automatically unlock the connector when the EV disconnects the cable. Default true.  ​                                   |

⚡ Load Balancing & External Limits
| Parameter                 | Example Value(s) | Min  | Max   | Description                                                                                                                             |
| ------------------------- | ---------------- | ---- | ----- | --------------------------------------------------------------------------------------------------------------------------------------- |
| GExternalLimitPowerEnable | 0, 1             | 0    | 1     | Enable/disable load balancing based on external power metering. 1 = active.                               |
| GExternalLimitPower       | 10, 11           | 1 kW | 50 kW | Power limit for load balancing in kW. The charger automatically reduces charging when this is exceeded.   |
| GExternalSamplingCurWring | 1                | 0    | 1     | Wiring/measurement method for external current sensing. 1 = external meter active.                        |
| GLowPowerReserveEnable    | —                | 0    | 1     | Reserve a portion of power for household use during load balancing.  ​                                      |

☀️ Solar / PV Integration
| Parameter           | Example Value(s)  | Min | Max | Description                                                                                                          |
| ------------------- | ----------------- | --- | --- | -------------------------------------------------------------------------------------------------------------------- |
| GSolarBoost         | 1Enable, 1Disable | —   | —   | Enable Solar Boost: the charger charges faster when excess solar energy is available.   ​ |
| GSolarMode          | 10, 11            | 10  | 11  | Solar charging mode: 10 = solar only, 11 = mixed (solar + grid).   ​                      |
| GSolarLimitPower    | 1.4               | —   | —   | Minimum available solar power (kW) required before solar charging activates.   ​          |
| GSolarThresholdCurr | —                 | —   | —   | Threshold current (A) for activating solar charging.  ​                                  |

🕐 Off-Peak / Time-Based Charging
| Parameter         | Example Value(s)         | Min  | Max  | Description                                                                                                                           |
| ----------------- | ------------------------ | ---- | ---- | ------------------------------------------------------------------------------------------------------------------------------------- |
| GOffPeakEnable    | 1Enable, 0Disable        | 0    | 1    | Enable/disable off-peak charging. The charger only charges within the configured off-peak time window.  ​ |
| GOffPeakTime      | —                        | 0000 | 2359 | Time window for off-peak charging in format HHmm-HHmm.  ​                                                 |
| GOffPeakCurr      | —                        | 6 A  | 32 A | Maximum charging current during off-peak hours.  ​                                                        |
| GPeriodTime       | 1time10000-2359          | —    | —    | Defined time period(s) for scheduled charging. Can contain multiple time slots.                         |
| GTimeSharingPrice | time10000-2359price10.20 | —    | —    | Time-based electricity tariff linked to charging periods. Format: timeHHmmHHmm-priceX.XX.  ​              |

🔑 Access & Authentication
| Parameter | Example Value(s) | Min | Max | Description                                                                                                |
| --------- | ---------------- | --- | --- | ---------------------------------------------------------------------------------------------------------- |
| GRFEnable | true, false      | —   | —   | Enable/disable the RFID/RF card reader for charging session authorization.   |

🌐 Network & Connectivity
| Parameter          | Example Value(s) | Min | Max | Description                                                                             |
| ------------------ | ---------------- | --- | --- | --------------------------------------------------------------------------------------- |
| GNetworkMode       | —                | —   | —   | Network mode selection: WiFi, 4G/LTE, or wired LAN.  ​      |
| GServerURL         | (URL)            | —   | —   | OCPP backend server URL the charger connects to.          |
| GWifiSSID          | —                | —   | —   | Name (SSID) of the WiFi network the charger connects to.  ​ |
| GWifiPassword      | —                | —   | —   | Password for the WiFi network.  ​                           |
| G4GUserName        | —                | —   | —   | Username for the 4G/LTE mobile data connection.  ​          |
| G4GPassword        | —                | —   | —   | Password for the 4G/LTE connection.  ​                      |
| G4GAPN             | —                | —   | —   | APN name for the 4G/LTE mobile provider.  ​                 |
| GChargerNetDNS     | —                | —   | —   | DNS server address for wired network connection.  ​         |
| GChargerNetMask    | —                | —   | —   | Subnet mask of the network.  ​                              |
| GChargerNetGateway | —                | —   | —   | Default gateway IP address.  ​                              |
| GChargerNetMac     | —                | —   | —   | MAC address of the charger (read-only).  ​                  |

📊 Metering & Monitoring
| Parameter           | Example Value(s) | Min | Max | Description                                                                                            |
| ------------------- | ---------------- | --- | --- | ------------------------------------------------------------------------------------------------------ |
| GMeterValueInterval | —                | 1 s | —   | Interval in seconds at which the charger reports meter values via OCPP.  ​ |
| GPowerMeterType     | —                | —   | —   | Type of external energy meter connected (Modbus, pulse, etc.).  ​          |
| GPowerMeterAddr     | —                | —   | —   | Modbus address or identifier of the external energy meter.  ​              |

🖥️ Display & User Interface
| Parameter       | Example Value(s) | Min | Max | Description                                                                                |
| --------------- | ---------------- | --- | --- | ------------------------------------------------------------------------------------------ |
| GLCDCloseEnable | Enable, Disable  | —   | —   | Automatically turn off the LCD display after inactivity.  ​    |
| LightIntensity  | —                | 0   | 100 | Brightness of the LED ring/indicator light as a percentage.  ​ |

🌍 Time & Region
| Parameter           | Example Value(s) | Min | Max | Description                                                                           |
| ------------------- | ---------------- | --- | --- | ------------------------------------------------------------------------------------- |
| GTimeZone           | —                | —   | —   | Timezone of the charger (e.g. Europe/Amsterdam).  ​       |
| GDaylightSavingTime | —                | 0   | 1   | Automatically apply daylight saving time. 1 = enabled.  ​ |

📡 Demand Response (DRM)
| Parameter       | Example Value(s) | Min | Max   | Description                                                                                         |
| --------------- | ---------------- | --- | ----- | --------------------------------------------------------------------------------------------------- |
| GDRM3Percentage | —                | 0 % | 100 % | DRM3: reduction of charging power on grid request (e.g. 75% of max).  ​ |
| GDRM4Percentage | —                | 0 % | 100 % | DRM4: further reduction or full stop of charging on grid request.  ​    |

Note: Min/max values not directly visible in the dumps are inferred from OCPP 1.6 spec and Growatt integration code. Example values in the table are literally observed in the captured OCPP traffic. Parameters GRFEnable and GPeriodTime are explicitly queried via GetConfiguration on every reconnect.

------------------------------------------------------------------------

## OCPP Behavior (Growatt-Specific)

### 1. Automatic (Push)

Sent by THOR without triggers:

-   BootNotification
-   Heartbeat
-   StatusNotification
-   StartTransaction / StopTransaction
-   DataTransfer: `frozenrecord` (end of session)

------------------------------------------------------------------------

### 2. Triggered (Critical)

These **require explicit triggers**:

#### Live Meter Data

``` text
DataTransfer:
  vendorId = "Growatt"
  messageId = "get_external_meterval"
```

Response:

    used=0&wring=1&u-voltage=0&u-current=0&power=0

Without this call → **no live data**

------------------------------------------------------------------------

### 3. Configuration Pull

``` text
GetConfiguration
```

Returns all Growatt settings including: - G_MaxCurrent -
G_ExternalLimitPower - G_ExternalLimitPowerEnable - G_ChargerMode -
G_ServerURL

------------------------------------------------------------------------

## Home Assistant Integration Design

### Initial Discovery Flow

On THOR connect:

1.  Trigger StatusNotification
2.  Trigger get_external_meterval
3.  GetConfiguration

This mirrors Growatt Cloud behavior.

------------------------------------------------------------------------

### Periodic Updates

  Data            Method             Interval
  --------------- ------------------ ------------------------------
  Status          Push               event-based
  Live power      DataTransfer       **30 seconds (recommended)**
  Configuration   GetConfiguration   on-demand

------------------------------------------------------------------------

## Configuration Handling

Configuration keys are: - stored in the coordinator - selectively
exposed as sensors

Initial focus:

  Key                          Meaning
  ---------------------------- -----------------------------------
  G_MaxCurrent                 Max current per phase
  G_ExternalLimitPower         Load balancing limit
  G_ExternalLimitPowerEnable   Load balancing on/off
  G_ChargerMode                Charging mode
  G_ServerURL                  OCPP endpoint (read-only for now)

------------------------------------------------------------------------

## About `G_Authentication = 12345678`

-   NOT an OCPP security key
-   Used for local authorization (RFID / keypad)
-   Not required for OCPP server replacement
-   Safe to ignore in current design

------------------------------------------------------------------------

## Changing Configuration (Future)

OCPP supports:

``` text
ChangeConfiguration
```

Preliminary conclusions: - THOR accepts changes while connected - AP
mode is NOT required for most settings - Server URL *may* require
reconnect/reboot

This will be implemented incrementally.

------------------------------------------------------------------------

## Goal State

✔ Fully local OCPP server\
✔ No Growatt Cloud dependency\
✔ HA-native sensors & services\
✔ Deterministic behavior\
✔ Extensible configuration control

------------------------------------------------------------------------

## Status

Current state: - Live data working - Configuration readable - Trigger
logic confirmed - Architecture validated

Next steps: - Periodic task scheduler - ChangeConfiguration support -
Config entities (numbers/switches)
