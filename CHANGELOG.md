# Changelog

All notable changes to the Growatt THOR EV Charger integration will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.3.0] - 2026-03-14

### What's New
- **LCD On/Off Control**: Added switch to turn the LCD display on or off (user request — thanks @OleMadsen1971!)

### Improvements
- **Moved mode selector to Settings**: Mode selection requires a reboot and is not intended for use in automations. Moving it to Settings (Config Flow) makes this distinction clearer. For correct displaying parameters/diagnostics it might be needed to manual remove and add the integration again after applying this update. 
- **Improved robustness of Max Current and Load Balancing Limit writes**: Skips redundant OCPP `ChangeConfiguration` calls when the value is unchanged, and rolls back the optimistic UI update if the THOR rejects or errors the write

### Bug Fixes
- **Fixed minimum and maximum load balance limits**: Prevents THOR crashes caused by out-of-range values and minimum current now conform IEC 61851 standard (6A)
- **Fixed blocking call in event loop**: OCPP JSON schemas are now pre-loaded via executor during startup, preventing a blocking `open()` call inside the Home Assistant async event loop (fixes warning in `homeassistant.util.loop`) (thanks @Greg-null!)
- **Fixed spurious errors and orphaned futures on THOR reboot**: Disabled websockets-level ping (`ping_interval=None`, `ping_timeout=None`) since THOR manages keepalive via OCPP Heartbeat, added explicit task cancellation with `ensure_future`+`shield` to prevent `Future exception was never retrieved` errors, and introduced a linearly growing poll backoff (60s → 300s) on consecutive timeouts to minimise redundant requests during reboot cycles
- **Fixed missing guard on Start/Stop Charging buttons**: Pressing "Start charging" while a session is already active, or "Stop charging" without an active session, now logs a warning and returns early instead of sending a rejected OCPP command to the THOR
- **Fixed spurious ERROR on clean THOR disconnect**: `ConnectionClosedOK` (WebSocket 1001 "going away") is now handled at DEBUG level alongside `ConnectionClosedError`, preventing false error logs on integration reload or removal

---

## [1.2.0] - 2026-01-30

### What's New
- **🔐 AP Mode Control**: Activate Thor's Access Point mode directly from HA via integration configuration menu (includes safety confirmation dialog)
- **📋 Enhanced Diagnostics**: All 34 Thor configuration keys now logged in diagnostics (automatic password/sensitive data masking)
- **⚡ Write Queue System with Thor Protection**: 
  - All write commands (max current, load balancing, schedules, start/stop) now use a centralized queue
  - 20-second rate limiting between writes prevents Thor firmware instability
  - Automatic deduplication: rapid UI changes (e.g., sliding current 10→15→20A) only send the final value
  - Polling automatically pauses during config writes to protect Thor firmware
  - Example: Changing 7 settings rapidly → queue handles them safely with proper timing

### Improvements
- **Changed integration text**:
  - Charge mode "APP/RFID" renamed to "HA (Home Assistant)/RFID" for clarity
  - Renamed loadbalancing attribute for better readability
- **Code Quality**: Removed obsolete comments and improved code structure

### (bug) Fixes
- **Fixed multiple fast writes**: Write queue wasn't enabled for number and select entities - now all entities use the centralized queue system
- **Fixed 'STOP Charging' not working after HA restart**: Now handles missing transaction ID gracefully

---

## [1.1.0] - 2026-01-24

🎉 **First stable release!** 🎉

🛡️ **Major stability improvements!** This release introduces a write queue system that dramatically reduces Thor firmware crashes.

### Added

#### Write Queue System (Anti-Crash Protection)
- **Write queue with rate limiting**: All configuration writes are now queued and executed with a minimum 15-second interval
- **Intelligent write buffering**: Multiple rapid changes are automatically queued and executed sequentially
- **Enhanced polling pause**: 20-second polling pause after each write operation (increased from 10s)
- **Queue status logging**: Real-time visibility of queued write operations and wait times

#### UI/UX Improvements
- **Auto-apply for charging schedule**: Time entities now automatically write to Thor without requiring "Apply" button
- **Optimistic UI updates**: Configuration changes (max current, load balancing) are immediately visible in UI while write is queued
- **Removed "Apply charging schedule" button**: No longer needed with auto-apply functionality
- **Smarter logging**: Polling pause messages now show once with countdown instead of repeating every second

### Changed
- **Energy sensor behavior**: `sensor.growatt_thor_ev_charger_energy_charged` now returns `0` instead of `unknown` when not charging (Energy Dashboard compatible)
- **Charging power sensor behavior**: `sensor.growatt_thor_ev_charger_charging_power` now returns `0` instead of `unknown` when not charging (Energy Dashboard compatible)
- **Current sensor behavior**: Phase current sensors (`L1`, `L2`, `L3`) now return `0` instead of `unknown` when no current flows (Energy Dashboard compatible)
- **Write interval reduced**: Minimum time between writes reduced from 30s to 15s (more responsive, still safe)
- **Polling pause duration**: Increased from 10s to 20s after configuration writes for better Thor firmware stability

### Fixed
- **Thor firmware crashes**: Write queue prevents rapid successive configuration changes that caused firmware reboots
- **Energy Dashboard compatibility**: Sensors now provide numeric zero values instead of unknown/unavailable states
- **Race conditions**: Sequential write operations no longer interfere with each other
- **Polling conflicts**: Grid polling no longer occurs during critical configuration write windows

### Technical Details
- **Write queue implementation**: Thread-safe deque with asyncio locks
- **Rate limiting**: Enforced 15-second minimum interval between writes
- **Post-write protection**: 20-second polling blackout after each configuration change
- **Queue persistence**: Write queue survives across multiple rapid user interactions

### Breaking Changes
- **Removed entity**: `button.growatt_thor_ev_charger_apply_charging_schedule` (functionality moved to automatic write queue)
- **Behavior change**: Time entities now write immediately to queue instead of waiting for manual apply

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

