# Changelog

All notable changes to the Growatt THOR EV Charger integration will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

_Target version: 1.7.0_

### Added
- **More interface languages**: Setup, entity names, states, and controls are now also available in Italian, Hungarian, Slovenian, French, and Spanish. Detailed technical help remains in English until it has been reviewed by native speakers.
- **Last charger fault**: A new diagnostic sensor keeps the most recent real charger fault, even after the charger recovers or Home Assistant restarts. Downloaded diagnostics include the available details for troubleshooting.
- **External meter status**: A new diagnostic sensor shows whether the external meter is working, has a Modbus fault, has stopped responding, or has not reported any data yet.
- **Mode-aware controls**: You can select the charging strategy, configure permitted grid power for PV Linkage, and enable warm-up after a full charge. Controls are disabled automatically when they do not apply to the selected mode.
- **Safer settings**: Settings that can be changed safely are available as controls. More complex or not yet fully verified Growatt settings remain read-only for now.
- **Confirmed setting changes**: Mode and installation settings cannot be changed during an active charging session. After a change, the integration reads the setting back from the charger to confirm that it was applied.
- **External meter controls**: Choose between a power meter, CT 2000:1, and CT 3000:1. When using a power meter, you can also select its model and Modbus address.
- **PV Linkage Boost controls**: Configure Disabled, Manual, or Smart Boost. Manual Boost uses a time window; Smart Boost uses a target energy and finish time. Changes are sent together when you press Apply.
- **Effective charging time**: A new sensor shows how long energy was actually transferred, excluding time when the vehicle remained plugged in without charging. The value is also included in diagnostics and CSV exports.
- **Charger information**: Manufacturer, model, firmware version, and serial number are available as read-only diagnostic sensors when reported by the charger.
- **Network information**: Network mode, IP address, subnet mask, gateway, DNS server, MAC address, and Wi-Fi SSID are available as read-only diagnostic sensors. Sensitive data remains hidden in downloaded diagnostics.

### Changed
- **Current range matches the charger**: The maximum-current control now stops
  at 16 A for 3/11 kW, 32 A for 7/22 kW, or 63 A for 44 kW models. Unknown
  models keep the conservative 32 A limit.
- **Clearer entity roles**: Measurements remain sensors, settings that can be changed appear as controls, technical values appear under diagnostics, and Start/Stop remain buttons.
- **Less duplicate information**: Read-only copies of writable settings are disabled by default. They can still be enabled manually when separate history or automations are needed.
- **Shared charging periods**: The same charger time windows may be used for Off-Peak charging or PV Linkage Manual Boost, depending on the selected mode. Their name and description now reflect this.
- **Session duration display**: Session durations are shown in hours and can use Home Assistant's normal unit conversion. CSV exports continue to store minutes.
- **Quieter activity history**: The activity log records confirmed setting changes instead of every internal step while a change is being sent to the charger.
- **Load-balancing guidance**: The load-balancing controls now explain that they are available only in Fast and Off-Peak modes, not in PV Linkage modes.

### Fixed
- **Home Assistant 2026.8 compatibility**: Removes a warning when upgrading an existing External Meter device while keeping the existing device and entities intact.
- **Controls while the charger has a fault**: Settings and Start Charging are unavailable while the charger reports a fault. Stop Charging remains available, and the other controls return automatically after recovery.
- **PV Linkage with a meter fault**: PV Linkage cannot be newly selected while the external meter reports a fault or repeatedly stops responding. One or two temporary timeouts do not block the mode, and an active mode is never changed automatically.
- **Clearer PV mode names**: PV Linkage allows the configured amount of grid power, while PV Linkage+ uses solar surplus only. Manual and Smart Boost may still use grid power.
- **Delayed charging-strategy changes**: The selected strategy now remains visible while the charger processes it. A newer selection replaces an older queued change correctly.
- **Session-duration upgrades**: Existing installations are migrated to the new duration display more reliably, including systems affected by an earlier incomplete migration.

---

## 🎉 [1.6.0] - 2026-09-03

**Major diagnostics and session-tracking release, built end-to-end by @felixhix. Huge thanks to him for driving this release from start to finish.**

### Added
- **Hardware and firmware overview**: Documents the known THOR hardware versions and reported V2, V4, V5, and V6 firmware families, including important compatibility differences.
- **More complete diagnostics**: Charger settings are retained for troubleshooting, including settings the integration does not yet understand. Passwords and other sensitive values are hidden. (PR #42)
- **New diagnostic sensors**: Adds read-only sensors for Working Mode, Authorization Mode, Power Meter Type, Power Meter Address, and External Sampling Method. Names and states are available in English, German, and Dutch. (PR #42)
- **Connection details**: The Status sensor now shows whether the charger is connected and when Home Assistant last received a message or heartbeat. (PR #42, extended in #44)
- **Automatic connection timeout**: A charger that sends no messages for three minutes is disconnected so that Home Assistant no longer shows an old status as current. Connection details remain available in diagnostics. (PR #44)
- **External meter details**: The Grid Power sensor includes the latest update time and the original Growatt meter flags for troubleshooting. (PR #44)
- **Charger and session diagnostics**: Downloaded diagnostics now include the latest startup information, charger status, active transaction, and last completed transaction. This includes model, firmware, serial number, connector, energy readings, stop reason, and available fault details. (PR #45)
- **Missing startup information recovery**: Home Assistant asks the charger for its startup information after reconnecting if the charger does not send it automatically. (PR #45)
- **Complete meter samples**: All values sent by the charger are retained in diagnostics, including measurements that do not yet have their own Home Assistant entity.
- **More reliable session records**: Growatt's current and completed session records are stored separately and used by the existing session sensors, energy total, and CSV export.
- **Combined session view**: Matching OCPP and Growatt data is combined into one diagnostic session without mixing unrelated charging sessions.
- **Stable session IDs**: Every charging session receives a stable ID that also shows whether it came from Home Assistant, another system, or an older CSV entry.
- **Improved CSV exports**: Session source and ID are included in new exports. Existing CSV files are upgraded automatically without removing existing or custom columns.
- **PV and Off-Peak diagnostics**: Reported PV Linkage, Boost, and Off-Peak settings are available as translated read-only entities.
- **Warm-up and delayed-charging diagnostics**: Reported warm-up and charging-delay settings are available as read-only sensors. Random Delay remains read-only because the app's behavior could not be verified reliably.
- **Helpful entity descriptions**: Read-only mode, PV, Off-Peak, external-meter, warm-up, and delayed-charging entities include short explanations in English, German, and Dutch.

### Changed
- **External Meter device name**: Renames the separate Load Balancing device to External Meter because its measurements are also used by PV Linkage. Existing entity IDs and custom device names are kept. (PR #42)
- **Translated entity names and states**: Existing charger and external-meter sensors now use English, German, or Dutch based on the Home Assistant language. Existing entity IDs do not change. (PR #41, #42)
- **External meter updates in every mode**: Grid measurements are requested in every charging mode, including PV Linkage, instead of only while load balancing is enabled. (PR #44)
- **Readable last-session modes**: The activity log and history show translated charging and operating mode names instead of Growatt's numeric codes. Unknown codes are shown as unknown rather than guessed.
- **System currency**: Electricity price and session cost use the currency configured in Home Assistant. EUR is used only when no system currency is available.

### Fixed
- **Slow Home Assistant startup**: The connection monitor now starts in the background instead of delaying integration setup for up to five minutes.
- **External measurement selection**: Corrects the mapping for Power Meter, CT 2000:1, and CT 3000:1. (PR #42)
- **False zero meter values**: Grid power, voltage, and current remain unavailable until the charger sends real values instead of showing artificial zeroes. (PR #44)
- **False zero temperature**: Temperature remains unavailable until the charger sends an actual temperature value. (PR #42)
- **Disconnected charger shown as available**: The Status sensor becomes unavailable when the OCPP connection times out, while the previous status remains in diagnostics. (PR #44)
- **PV, Boost, and Off-Peak values**: Combined Growatt values are now displayed as stable, readable Home Assistant states.
- **Power Distribution mode**: This working mode is now recognized and translated instead of making the Working Mode sensor unavailable.
- **Transaction IDs after reconnecting**: Home Assistant no longer starts transaction numbering at `1` after every reconnect, preventing reused IDs.
- **Last-session values after a restart**: Last-session sensors survive Home Assistant restarts, and repeated Growatt records no longer increase the energy total or create duplicate CSV rows.

### Scope notes
- Version 1.6.0 adds diagnostics and read-only information. It does not add new writable charger settings.
- Diagnostics keep the latest relevant information, not a full history of every OCPP message.

---

## [1.5.4] - 2026-06-12

### Fixed
- **Single-phase Growatt THOR chargers**: Now correctly display Power, Voltage, and Current by mapping generic OCPP measurands (without phase) to L1 entities.

---

## [1.5.3] - 2026-06-05

### Fixed
- **ocpp fix**: `prevent crash on null configuration payload` Prevent the OCPP server from crashing when the THOR returns an empty, null, or unexpected GetConfiguration response during startup or reconnect. Thanks @spatu

---

## [1.5.2] - 2026-05-07

### Fixed
- **AP Mode activation**: `AttributeError: module 'ocpp.v16.call' has no attribute 'DataTransferPayload'` that prevented AP Mode from being activated via the config flow. The `ocpp` library removed the `Payload` suffix from all call classes in newer versions; `call.DataTransferPayload` is now correctly referenced as `call.DataTransfer`. (Thank you jordiBCN-GitHub for your bug report!)
---

## [1.5.1] - 2026-04-06

### Fixed
- **Prevent duplicate CSV entries from currentrecord**: the THOR firmware occasionally sends two identical `currentrecord` DataTransfer messages within seconds after a session ends. A deduplication check on `transactionId` + `endtime` now prevents the same frozen record from being processed and written to CSV twice.
Note: You still need to manually remove the duplicate records from the CSV (/homeassistant/growatt_thor_sessions.csv). This is fairly easy to do with the file editor (found in the Home Assistant app store).

---

## [1.5.0]  - 2026-03-26

### Fixed
- **Prevent duplicate writes after GetConfiguration**: after a successful ChangeConfiguration (Accepted or RebootRequired), the coordinator value is now explicitly confirmed to the written value, preventing GetConfiguration responses from reverting the optimistic update and causing redundant writes on the next automation cycle.

### What's New
- **Electricity price sensor**: A new sensor Elektricteitstarief displays the current electricity tariff (EUR/kWh) as reported by the THOR, with 2 decimal precision.
- **Electricity price control**: A new number entity Elektricteitstarief allows setting the electricity tariff (range: -2.00 to +2.00 EUR/kWh, step: 0.01) via the UI or an automation. The value is written to the THOR as time1=00:00-23:59&price1=X.XX

---

## [1.4.2]  - 2026-03-24

### Fixed
- **Explicit GetConfiguration key lists**: replaced unfiltered request with two targeted calls (13 operational + 30 informational keys), fixing FormatViolationError on THOR_07AS firmware and excluding G_WifiPassword for security.

---

## [1.4.1] - 2026-03-23

### Fixed
- **Migrated to ocpp library >=2.0.0**: removed deprecated `*Payload` suffix from all OCPP 1.6 call and call_result classes, resolving compatibility issues when running alongside other OCPP integrations.

---

## [1.4.0] - 2026-03-21

## Please note! It is best to remove the integration and add it again after this update, as a new required field (Location) has been added to the setup.

### What's New
- **Automatic session logging to CSV**: Every completed charging session is now automatically appended to `/config/growatt_thor_sessions.csv`. This file serves as a permanent local log of all charging sessions and survives restarts and updates.
- **Charging data export**: Added a new action `growatt_thor.export_sessions` that generates a filtered CSV export for a specified date range. This export is intended for annual subsidy reporting programs (such as ERE certificates in the Netherlands) that require per-session charging data including charger ID, location, start/end time and energy delivered. The exported file is saved to `/config/www/` and a direct download link is provided via a Home Assistant notification.
- **Location field in setup**: A new **Location** field has been added to the integration setup (and options flow). Enter the exact installation address of the charger — this address is included in every exported session report as required for official reporting. The location can be updated at any time via **Settings → Devices & Services → Growatt THOR → Configure**.

### Usage
Export sessions via **Developer Tools → Actions**:

```yaml
action: growatt_thor.export_sessions
data:
  date_from: "2026-01-01"
  date_to: "2026-12-31"
```

After the action completes, a notification appears with a direct download link to the generated CSV file.
See README.md for full documentation including a Lovelace UI export panel example.

---

## [1.3.0] - 2026-03-20

## Please note! It is best to remove the integration and add it again after this update.

### What's New
- **LCD On/Off Control**: Added switch to turn the LCD display on or off (user request — thanks @OleMadsen1971!)
- **Session statistics sensors**: Added dedicated sensors for each completed charging session: energy (kWh), cost, duration (minutes), start time, end time, plug time, unplug time, charge mode, work mode and transaction ID (thanks @Greg-null!)
- **Persistent total energy tracking**: Added `sensor.growatt_thor_ev_charger_total_energy_charged` — cumulative energy counter across all sessions, persistent across restarts and compatible with the Home Assistant Energy Dashboard (thanks @Greg-null!)

### Improvements
- **Moved mode selector to Settings**: Mode selection requires a reboot and is not intended for use in automations. Moving it to Settings (Config Flow) makes this distinction clearer. For correct displaying parameters/diagnostics it might be needed to manual remove and add the integration again after applying this update. 
- **Improved robustness of Max Current and Load Balancing Limit writes**: Skips redundant OCPP `ChangeConfiguration` calls when the value is unchanged, and rolls back the optimistic UI update if the THOR rejects or errors the write
- **Session data now uses proper numeric sensor states**: Values from `currentrecord` are stored as numeric floats instead of string attributes, enabling automations, statistics and long-term history in Home Assistant
- **Removed Last sessions history sensor**: Replaced by individual session sensors with proper state classes

### Bug Fixes
- **Fixed minimum and maximum load balance limits**: Prevents THOR crashes caused by out-of-range values and minimum current now conform IEC 61851 standard (6A)
- **Fixed blocking call in event loop**: OCPP JSON schemas are now pre-loaded via executor during startup, preventing a blocking `open()` call inside the Home Assistant async event loop (fixes warning in `homeassistant.util.loop`) (thanks @Greg-null!)
- **Fixed spurious errors and orphaned futures on THOR reboot**: Disabled websockets-level ping (`ping_interval=None`, `ping_timeout=None`) since THOR manages keepalive via OCPP Heartbeat, added explicit task cancellation with `ensure_future`+`shield` to prevent `Future exception was never retrieved` errors, and introduced a linearly growing poll backoff (60s → 300s) on consecutive timeouts to minimise redundant requests during reboot cycles
- **Fixed missing guard on Start/Stop Charging buttons**: Pressing "Start charging" while a session is already active, or "Stop charging" without an active session, now logs a warning and returns early instead of sending a rejected OCPP command to the THOR
- **Fixed spurious ERROR on clean THOR disconnect**: `ConnectionClosedOK` (WebSocket 1001 "going away") is now handled at DEBUG level alongside `ConnectionClosedError`, preventing false error logs on integration reload or removal
- **Fixed energy sensor not accumulating during charging session**: Energy.Active.Import.Register samples with context: Transaction.Begin (always 0 Wh) are now skipped in process_meter_values, preventing the correct cumulative value from being overwritten each interval. Reported by users with firmware THOR_07AS-V5.2.11-20241210-NOVO (thanks @Greg-null!)
- **Fixed incorrect state_class warning for session energy sensor**: Removed `device_class: energy` from `Last Session Energy` sensor to comply with Home Assistant sensor class requirements
- **Removed confusing Host field from setup**: The OCPP server always binds to `0.0.0.0` (all interfaces), making the Host field ineffective. Removing it prevents users from accidentally entering the THOR's IP address, which would cause the integration to fail silently

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
