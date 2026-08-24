# Changelog

All notable changes to the Growatt THOR EV Charger integration will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## 🎉 [Version number] - yyyy-mm-dd

### Added
- **Structured charger configuration registry**: Preserve every returned OCPP and Growatt configuration value with its raw and parsed value, charger-provided read-only flag, type metadata, and enum label. Unknown keys are retained instead of being discarded after logging. (PR #42)
- **Redacted configuration diagnostics**: Include the retained configuration snapshot, unknown keys, and requested key groups in Home Assistant diagnostics while redacting sensitive and unclassified values. (PR #42)
- **Read-only configuration entities**: Add five diagnostic sensors — Working Mode, Authorization Mode, Power Meter Type, Power Meter Address, and External Sampling Method — sourced from the retained configuration registry. Enum states are translated in English, German, and Dutch. (PR #42)
- **Connection health on the status sensor**: The Status sensor now exposes connected, connection_started_at, last_message_at, last_message_action, and last_heartbeat_at as attributes, and uses a translated enum state (Available, Preparing, Charging, Suspended by charger/vehicle, Finishing, Reserved, Unavailable, Faulted, Idle) in English, German, and Dutch. (PR #42, extended in #44)
- **OCPP connection liveness tracking**: Track inbound OCPP activity independently from the last reported charger status, and close the local WebSocket after 180 seconds without any OCPP message (Heartbeat or otherwise). Connection and heartbeat timestamps are included in diagnostics. (PR #44)
- **External meter diagnostic attributes**: Retain Growatt's raw used and wring fields from get_external_meterval and expose them as vendor_used/vendor_wring attributes on the Grid Power sensor, alongside a last_updated_at timestamp. (PR #44)
- **OCPP boot, status, and transaction diagnostics**: Retain the latest complete BootNotification and StatusNotification requests, plus active and last-completed Start/StopTransaction metadata, in a normalized and redacted form included in Home Assistant diagnostics. Preserves firmware, model, and serial metadata, connector IDs, meter start/stop values, stop reasons, error codes, vendor error codes, and vendor-specific fields (e.g. ChargeWait) without changing existing operational entities. (PR #45)
- **Automatic BootNotification recovery**: Request a BootNotification via TriggerMessage once when a reconnecting charger does not send one on its own, ensuring diagnostics always have boot metadata available. (PR #45)
- **Lossless MeterValues diagnostics**: Normalize every OCPP meter sample with its measurand, value, unit, phase, context, location, timestamp, and original fields. Known samples continue to update Home Assistant entities while unknown measurands remain available in diagnostics.
- **Structured Growatt session records**: Preserve `currentrecord` and `frozenrecord` separately, including blank, duplicate, and previously unknown fields. Known session values continue to feed the existing last-session sensors, CSV export, and persistent energy total.
- **Correlated session diagnostics**: Combine matching OCPP transaction metadata, the latest transaction-scoped meter energy, and Growatt `currentrecord`/`frozenrecord` values into one source-aware diagnostic view. Sessions are marked as `matched`, `ocpp_only`, or `growatt_only`; different transaction IDs and older records from a reused ID are never merged.
- **Mode-specific configuration sensors**: Expose reported PV Linkage, boost, and off-peak settings as read-only entities. Confirmed compound values are normalized into translated states while their original values remain available as raw attributes.
- **Warm-up and delayed-charging diagnostics**: Expose reported `G_FullContinueChargeEnable` and `G_RandDelayChargeTime` values as read-only diagnostic sensors. No Random Delay control is created because the tested ShinePhone app writes the same value for both switch directions.
- **Localized entity explanations**: Add concise English, German, and Dutch information attributes to the read-only mode, PV, off-peak, external-meter, warm-up, and delayed-charging entities.

### Changed
- **External meter device naming**: Rename the logical Growatt THOR Load balancing device to Growatt THOR External Meter because the measurements are shared by load balancing and PV Linkage. Existing default device metadata is migrated in place; user-assigned names, device identifiers, and entity IDs remain unchanged. (PR #42)
- **Localized entity names and status values**: Replace hard-coded English names on existing charger and external-meter sensors with Home Assistant translation keys, and translate OCPP status values. Available in English, German, and Dutch without changing unique IDs or existing entity IDs. (PR #41, #42)
- **External meter polling scope**: Request get_external_meterval in every charger working mode, both on connect and periodically, instead of only while load balancing is enabled — PV Linkage now receives the same grid measurements. (PR #44)
- **Translated last-session modes**: Show known Growatt `chargemode` and `workmode` values as localized enum states in entity history and the activity log. The original numeric vendor code remains available as a `raw_value` attribute, and unverified work-mode codes are shown as unknown instead of being guessed.
- **Currency-aware cost entities**: Use the Home Assistant system currency for electricity-price and last-session-cost units because the charger reports numeric prices without a currency. EUR remains the fallback when Home Assistant has no configured currency.

### Fixed
- **External sampling method mapping**: Use the OCPP value mapping 0=CT 2000:1, 1=PowerMeter, and 2=CT 3000:1. The charger web page uses a separate, shifted dropdown because it includes an additional NULL option. (PR #42)
- **External meter availability**: Keep grid power, voltage, and current unavailable until the charger returns the corresponding field and the connection is active, instead of displaying synthetic zero values. (PR #44)
- **Temperature without samples**: Report the temperature sensor as unavailable until the charger sends an actual OCPP MeterValues temperature sample instead of displaying an artificial 0 °C. (PR #42)
- **Stale connections shown as available**: The Status sensor now becomes unavailable when the OCPP connection has timed out, while diagnostics retain the last charger-reported status for troubleshooting. (PR #44)
- **Compound mode values**: Parse PV Linkage mode and boost variants, off-peak enable values, boost-suffixed working modes, and chained off-peak time windows into stable Home Assistant states without discarding their raw Growatt representation.
- **Power Distribution working mode**: Recognize the observed `G_WorkingMode=Power Distribution` value as a translated read-only state instead of making the Working Mode sensor unavailable.
- **Transaction IDs across reconnects**: Allocate Home Assistant OCPP transaction IDs from persistent storage instead of restarting at `1` for every WebSocket connection. The next ID is saved before `StartTransaction.conf` is returned.

### Scope notes
- **No new ChangeConfiguration calls or writable controls were introduced by PR #41, #42, #44, or #45.**
- **The existing 14-key operational and 30-key informational GetConfiguration request groups remain unchanged, including the THOR firmware limit of 30 keys per request.**
- **Diagnostics retain only the latest relevant snapshot per message type, not a full message history.**

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
