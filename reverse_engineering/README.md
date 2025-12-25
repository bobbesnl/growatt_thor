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
[Service]
ExecStart=/usr/bin/socat TCP-LISTEN:9000,fork,reuseaddr TCP:real.server.ip:9000
```

Purpose: - MITM inspection - No firmware changes required - Safe and
reversible

------------------------------------------------------------------------

### 2. tcpdump capture

Used to record raw traffic for offline analysis.

``` bash
tcpdump -i eth0 -s 0 -w ocpp-session.pcap tcp port 9000
```

Notes: - `-s 0` is mandatory (otherwise payload is truncated) - PCAP
files can be analyzed later without live access

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
