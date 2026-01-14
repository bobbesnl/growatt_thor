# Changelog

All notable changes to the Growatt THOR EV Charger integration will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0-beta] - 2026-01-14

🎉 **Beta release!** The integration has moved from alpha to beta, expect bugs (please report them).

### Added

#### Monitoring & Sensors
- **Real-time charger status** (Idle, Preparing, Charging, Finishing, Faulted, Unavailable)
- **Power monitoring**: Total power and per-phase (L1, L2, L3) in Watts
- **Current monitoring**: Per-phase current draw in Amperes
- **Voltage monitoring**: Per-phase voltage monitoring
- **Energy tracking**: Session energy in kWh with automatic reset per charging session
- **Temperature sensor**: Internal charger temperature monitoring in °C
- **Transaction tracking**: Active transaction ID and session details
- **Grid monitoring**: Real-time grid power, voltage, and current per phase via external meter
- **Session history**: Last 5 charging sessions with energy (kWh), cost, timestamps, and modes

#### Controls
- **Max current control**: Adjustable maximum charging current (6-32A) via number entity
- **Load balancing**: Dynamic grid import limit (kW) to prevent overload
- **Load balancing toggle**: Enable/disable dynamic load balancing via switch
- **Charger mode selection**: Switch between Plug & Charge, RFID only, and APP/RFID charging modes
- **Charging schedule**: Configurable automatic start/stop times via time entities
- **Manual charging control**: Start and stop buttons for manual charging session control
- **Schedule apply button**: Atomic update of charging schedule to prevent configuration conflicts

#### Configuration
- **Configurable poll interval**: User-selectable grid polling interval (5-3600 seconds)
  - Configured during initial setup or via options flow
  - Default: 30 seconds (recommended balance)
  - Note: Only affects display update frequency, not load balancing functionality
- **Options flow**: Ability to reconfigure poll interval after initial setup
- **Config flow validation**: Minimum poll interval validation (5 seconds) to protect Thor firmware

#### Stability & Protection
- **Anti-crash protection**: Automatic polling pause after configuration changes
  - 10-second pause after configuration writes (prevents Thor firmware crashes)
  - 5-second pause after start/stop commands
- **Smart polling**: Only polls external meter when load balancing is enabled
- **TIER 2 error recovery**: Robust error handling for connection interruptions
- **Automatic reconnection**: Handles Thor disconnects and reconnects gracefully
- **Post-connect initialization**: Automatic configuration fetch after first heartbeat

#### OCPP Implementation
- **Full OCPP 1.6J support** (JSON over WebSocket)
- **Implemented OCPP messages**:
  - `BootNotification`, `Heartbeat`, `StatusNotification`
  - `StartTransaction`, `StopTransaction`, `MeterValues`
  - `Authorize`, `DataTransfer` (including Growatt vendor extensions)
  - `RemoteStartTransaction`, `RemoteStopTransaction`
  - `GetConfiguration`, `ChangeConfiguration`
  - `TriggerMessage`
- **Growatt-specific features**:
  - `G_MaxCurrent` - Maximum charging current configuration
  - `G_ExternalLimitPower` - Load balancing power limit
  - `G_ExternalLimitPowerEnable` - Load balancing on/off
  - `G_ChargerMode` - Charging mode
  - `G_AutoChargeTime` - Scheduled charging time range
  - `get_external_meterval` - Grid meter data retrieval
  - `frozenrecord`/`currentrecord` - Session history data

### Changed
- **Moved from alpha to stable**: Extensively tested and production-ready
- **Improved logging**: Better structured logging with emoji indicators for easier debugging
- **Session energy reset**: Energy counter now automatically resets at the start of each new charging session (not at stop)
- **Power/current reset**: Power and current values reset to zero when charging stops
- **Configuration handling**: More robust parsing of Growatt configuration responses

### Fixed
- **OptionsFlow crash**: Fixed `AttributeError: property 'config_entry' of 'GrowattThorOptionsFlow' object has no setter`
- **Thor firmware crashes**: Prevented by implementing polling pause mechanisms
- **MeterValues parsing**: Improved parsing of both `sampled_value` and `sampledValue` formats (dict and attribute access)
- **Transaction ID tracking**: Proper transaction ID storage and retrieval for stop commands
- **Wiring detection**: Correct 1-phase vs 3-phase detection from external meter data

### Technical Details
- **Minimum Home Assistant version**: 2023.8.0 (recommended: 2024.1.0+)
- **Minimum HACS version**: 1.34.0
- **Python OCPP library**: 0.26.0 - 0.29.x
- **Platforms**: sensor, number, switch, select, time, button
- **IoT Class**: `local_push` (local control without cloud dependency)

### Documentation
- **Complete README**: Installation guide, configuration instructions, troubleshooting
- **User guide**: Entity descriptions, example automations, best practices
- **Failsafe instructions**: How to restore Growatt cloud connectivity if needed
- **Technical details**: OCPP message overview, Growatt vendor extensions

---

## [0.1.0] - 2024-12-XX

⚠️ This integration was in **ALPHA** status.

### Added
- Initial OCPP 1.6 server implementation
- Basic connection support for Growatt THOR EV charger
- Logging of `BootNotification`, `Heartbeat`, `StatusNotification` and `MeterValues`
- Basic sensor entities for status and power

### Known Issues
- No stability guarantees
- Breaking changes expected
- Limited error handling
- No anti-crash protection

❗ Alpha version - not suitable for production use.

---

## Links
- [GitHub Repository](https://github.com/bobbesnl/growatt_thor)
- [Issue Tracker](https://github.com/bobbesnl/growatt_thor/issues)

---

**Legend:**
- 🎉 Major milestone
- ⚠️ Important notice
- ❗ Breaking change

