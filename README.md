[!["Buy Us A Coffee"](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/bobbesnl)

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
![Version](https://img.shields.io/badge/version-1.7.0--dev.2-blue)


⚠️ **Please read this document first before installing this integration!**

<img src="icons/custom_branding/logo.png" alt="Growatt THOR" width="320">

⚡ **Unofficial Home Assistant integration for the Growatt THOR EV charger**  

This integration allows you to connect a Growatt THOR EV charger **directly to Home Assistant** using **OCPP 1.6 over WebSocket**, providing local control without relying on the Growatt cloud.

Tested on:
- THOR 22AS with firmware `THOR_22AS-V2.2.16-20240902`

The THOR family has multiple hardware generations and firmware branches.
Compatibility with another model or firmware must not be inferred from the
version number alone. See the
[hardware and firmware variants](reverse_engineering/hardware_firmware_variants.md)
for known community reports and compatibility guidance.

Do you have another Growatt EV charger? Please test it with the integration and let me know if it is working. If you open up an issue and provide logs, I will try to add your charger to be supported (Growatt only!).

> ⚠️ This is an **unofficial community project**. Growatt is not affiliated with or endorsing this integration in any way.

---

## ⚠️ Known Issues

### Thor Firmware Instability & Random Reboots

The Growatt Thor charger has **known firmware bugs** that can cause crashes and unexpected reboots, particularly during:
- Multiple rapid configuration changes
- Concurrent polling and command execution
- High message frequency on the OCPP connection

**Protective Measures Implemented:**
- Write queue with 20-second rate limiting
- Automatic polling pause during config writes
- Command deduplication for rapid UI changes
- Smart timing delays

⚠️ **Important**: While these protections significantly reduce crashes, they **cannot guarantee** complete stability due to Thor's firmware limitations.

**📢 Help Us Improve!**
Experiencing crashes or random reboots? Please [open an issue](https://github.com/bobbesnl/growatt_thor/issues) with:
- Thor model and firmware version, if known
- Enclosure layout, exterior controls, or PCB marking, if safely accessible
- Home Assistant logs (around crash time)
- Actions that triggered the reboot
- Relevant entity states before and after the reboot

Your feedback helps identify patterns and improve integration stability! 🙏

---

## Features

### 📊 Real-time Monitoring
- **Charger status**: Idle, Preparing, Charging, Finishing, Faulted, Unavailable
- **Connection health**: Last OCPP message and heartbeat timestamps; inactive WebSockets are disconnected after 180 seconds without inbound activity
- **Power monitoring**: Total power and per-phase (L1, L2, L3) in Watts
- **Current monitoring**: Current draw per phase in Amperes
- **Voltage monitoring**: Voltage per phase
- **Energy tracking**: Session energy in kWh with automatic reset per session
- **Temperature**: Internal charger temperature in °C
- **Transaction tracking**: Current charging data and individual sensors for the most recently completed session
- **Energy Dashboard compatible charging sensors**

### 🔌 Grid & Load Balancing
- **External meter monitoring**: Real-time grid power, voltage, and current per phase
- **Dynamic load balancing**: Set maximum grid import limit (kW) to prevent overload
- **Smart polling**: Configurable polling interval (minimum 5 seconds; recommended setting 30 seconds)
  - ⚠️ **Note**: Polling interval only affects the frequency of grid data **display updates** in Home Assistant. Load balancing functionality itself operates independently and responds in real-time regardless of the polling setting.

### ⚙️ Configuration & Control
- **Max current control**: Set maximum charging current (6-32A)
- **Charging schedule**: Configure automatic start/stop times
- **Charger modes**: Switch between Plug & Charge, RFID only, HomeAssistant(HA)/RFID mode
- **Configuration diagnostics**: Preserve all returned OCPP and Growatt configuration values, including unknown keys and charger-provided read-only flags
- **OCPP message diagnostics**: Retain the latest boot and status payloads plus active and last-completed transaction metadata; sensitive identifiers are redacted from downloaded diagnostics
- **Meter sample diagnostics**: Preserve the latest complete `MeterValues` payload, including unknown measurands and vendor fields that do not have Home Assistant entities
- **Growatt session diagnostics**: Preserve `currentrecord` and `frozenrecord` as separate structured records while keeping the existing last-session sensors and CSV export
- **Read-only configuration sensors**: Show working mode, authorization mode, PV Linkage, boost, off-peak, and external meter settings without exposing unverified write controls
- **Manual charging control**: Start and stop charging sessions via buttons
- **Load balancing toggle**: Enable/disable dynamic load balancing
- **Auto update THOR time**: Auto sync time with server time at every heartbeat and with reboot (ocpp protocol)
- **AP Mode Activation**: Added ability to enable AP (Access Point) mode directly from Home Assistant via integration configuration menu
    - Accessible through Settings → Devices & Services → Growatt THOR → Configure
    - Includes safety confirmation dialog to prevent accidental activation
    - Uses OCPP DataTransfer with messageId="appconfigmode" (discovered via PCAP analysis)
    - THOR broadcasts WiFi network (typically serialno based SSID) for direct configuration when activated

### 📈 Session History
- **Current session tracking**: Real-time updates during active charging

## 📋 Session Logging & Data Export

This integration automatically logs every completed charging session to a local CSV file. This is useful for subsidy programs (such as ERE certificates in the Netherlands) that require annual reports with per-session charging data.

### How It Works

After each completed charging session, the following data is automatically appended to `/config/growatt_thor_sessions.csv`:

| Field | Description |
|---|---|
| `charger_id` | Unique charger identifier (serial number) |
| `location` | Charger address as configured during setup |
| `start_time` | Charging session start time |
| `end_time` | Charging session end time |
| `energy_kwh` | Energy delivered during session (kWh) |
| `cost` | Session cost as reported by charger |
| `duration_minutes` | Session duration in minutes |
| `transaction_id` | OCPP transaction ID |
| `session_id` | Stable internal ID with an `ha-`, `ext-`, or `legacy-` prefix |
| `session_source` | `home_assistant`, `external_or_unknown`, or `legacy_unknown` |

The OCPP `transaction_id` remains unchanged for protocol-level analysis. The
additional `session_id` prevents equal numeric IDs assigned by different
central systems from colliding in exports. Existing CSV files are extended on
the next completed session. Since their original source cannot be reconstructed
reliably, historical rows are marked `legacy_unknown`.

### Initial Setup

When adding the integration, enter the **exact installation address** of the charger in the **Location** field. This address will be included in every exported session report.

You can update the location at any time via **Settings → Devices & Services → Growatt THOR → Configure**

### Exporting Session Data

Use the built-in action to export sessions for a specific date range:

**Via Developer Tools → Actions:**

```yaml
action: growatt_thor.export_sessions
data:
  date_from: "2026-01-01"
  date_to: "2026-12-31"
```

After the action completes, a notification appears in Home Assistant with a direct download link to the generated CSV file.

**Note:** The export file is saved to `/config/www/` and is accessible via `/local/` in your browser. The file is named `growatt_thor_export_YYYY-MM-DD_YYYY-MM-DD.csv`.

**Note:** for spreadsheet users: When opening the CSV in LibreOffice Calc or Microsoft Excel, ensure the decimal separator is set to . (dot) to correctly display energy values such as 0.068.

### Lovelace UI — Export Panel

**Add a export panel for a convenient export interface without needing Developer Tools**

First add this script: **Settings -> Automations and scenes -> Scripts -> Add script**
```yaml
alias: Growatt Export Sessions
sequence:
  - action: growatt_thor.export_sessions
    data:
      date_from: "{{ states('input_text.growatt_export_date_from') }}"
      date_to: "{{ states('input_text.growatt_export_date_to') }}"
mode: single
```

Then add the required helpers in **Settings → Helpers → Add Helper → Text:**
- **input_text.growatt_export_date_from** — default value: current year start e.g. 2026-01-01
- **input_text.growatt_export_date_to** — default value: today e.g. 2026-12-31


Add this card to your dashboard:

```yaml
type: vertical-stack
cards:
  - type: markdown
    content: |
      ## 📋 Export Charging Sessions
      Fill in the date range and press **Export** to generate a CSV download.
  - type: entities
    entities:
      - entity: input_text.growatt_export_date_from
        name: From (YYYY-MM-DD)
      - entity: input_text.growatt_export_date_to
        name: To (YYYY-MM-DD)
  - type: button
    name: Export Sessions
    icon: mdi:file-download-outline
    tap_action:
      action: call-service
      service: script.growatt_export_sessions
```

Example Export Output:

```csv
charger_id,location,start_time,end_time,energy_kwh,cost,duration_minutes,transaction_id,session_id,session_source
XGJ00003214700CA,"Kerkstraat 1, 1234 AB Amsterdam",2026-03-21 08:19:03,2026-03-21 09:42:02,3.170,0.63,83.0,1,ha-0123456789abcdef,home_assistant
XGJ00003214700CA,"Kerkstraat 1, 1234 AB Amsterdam",2026-03-22 07:05:11,2026-03-22 08:31:44,8.450,1.69,86.5,2,ext-fedcba9876543210,external_or_unknown
```

## 🛡️ Stability Features
- **Write queue system**: Intelligent buffering of all configuration writes with 20-second rate limiting
- **Anti-crash protection**: 20-second polling pause after each configuration change to prevent Thor firmware crashes
- **Sequential write operations**: Multiple rapid changes are automatically queued and executed safely
- **TIER 2 error recovery**: Robust error handling for connection issues
- **Smart polling**: Only polls external meter when load balancing is enabled
- **Queue visibility**: Real-time logging of queued operations and wait times

---

## Architecture

```
Growatt THOR EV Charger
    ↓ OCPP 1.6 (WebSocket, unencrypted)
Home Assistant (Local OCPP Server)
```

The integration runs a **local OCPP 1.6 server** inside Home Assistant. The Growatt THOR charger connects directly to this server instead of the Growatt cloud backend, providing:
- **Local control**: No internet dependency for basic operations
- **Privacy**: Charging data stays local
- **Reliability**: No cloud service interruptions
- **Speed**: Instant updates without cloud round-trips

---

## Installation

### Prerequisites
- Home Assistant (2024.4.1 or newer recommended)
- HACS (Home Assistant Community Store) installed (minimum v1.34.0 but most latest version is recommended)
- Working Growatt THOR EV Charger setup --> Fully configured to work with your (hybrid) inverter and with a working network connectivity to Growatt cloud (Shinephone app)
- Network access between Home Assistant server and the charger

### Via HACS (Recommended)

1. **Install the integration**
   - Open **Home Assistant**
   - Go to **HACS → Integrations**
   - Click **Explore & Download Repositories** (wording may differ per HACS version)
   - Search for **Growatt THOR** (or **Growatt THOR EV Charger**)
   - Click **Download**
   - Restart Home Assistant

### Alternative: Add repository manually to HACS (Custom repository)

Use this if you cannot find the integration in the default HACS list yet, or if you intentionally want to install from a fork/branch.

1. **Add custom repository**
   - Open **Home Assistant**
   - Go to **HACS → Integrations**
   - Click **⋮** (three dots) → **Custom repositories**
   - Add repository:
     - **URL**: `https://github.com/bobbesnl/growatt_thor`
     - **Category**: `Integration`
   - Click **Add**

2. **Install the integration**
   - Search for **Growatt THOR** (or **Growatt THOR EV Charger**) in HACS
   - Click **Download**
   - Restart Home Assistant

### Configure the integration

1. Go to **Settings → Devices & Services**
2. Click **+ Add Integration**
3. Search for **Growatt THOR**
4. Configure:
   - **Listen Port**: `9000` (default, or choose your own)
   - **Location**: Installation address used in session exports
   - **Grid Poll Interval**: `30` seconds (recommended)
     - Minimum: 5 seconds
     - Lower values = more frequent updates (higher load on THOR)
     - Higher values = less frequent updates (lower load)
     - **Important**: This only affects display update frequency, not load balancing functionality
5. Click **Submit**

Home Assistant is now ready and waiting for the charger to connect.

---

## Configuring the Growatt THOR Charger

### ⚠️ Important Notes

- Changing the server URL will **disconnect the charger from Growatt cloud**
- You will **lose access to the Growatt app** while using this integration
- Make sure you know how to **restore the original settings** via AP mode
- **Test the server URL** before saving to avoid lockout

### Configuration Methods

#### Method 1: Via AP Mode (Most Reliable)

Access methods and credentials vary between THOR hardware and firmware
variants. `12345678` is a documented default for the Wi-Fi access point on
older devices, but it is not guaranteed for every device or for the port 8080
web interface. See the
[hardware and firmware variants](reverse_engineering/hardware_firmware_variants.md).

1. **Enable AP Mode** on the Growatt THOR charger (via Shinephone app)
2. Connect your phone to the THOR's Wi-Fi using its configured credential (`12345678` is the documented default on older devices)
3. Open the **ShinePhone** or **Growatt** app
4. Navigate to **Network Settings** or **Server Settings**
5. Change the **Server URL** to:
   ```
   ws://<HOME_ASSISTANT_IP>:9000/ocpp/ws
   ```
   Example: `ws://192.168.1.101:9000/ocpp/ws`
6. **Save** and **reboot** the charger
7. Reconnect the charger to your normal Wi-Fi network

#### Method 2: Via Web Interface (Some Models)

Some Thor models have a web interface accessible via LAN cable:

1. Connect a network cable to the Thor charger
2. Set a static IP on your computer (e.g., `192.168.1.13`)
3. Open a browser and navigate to `http://192.168.1.5:8080`
4. Change the server URL as described above
5. Save and reboot

### Verification

After configuration, check Home Assistant:
- Go to **Settings → Devices & Services**
- The Growatt THOR device should appear with status "Connected"
- Sensors should start showing live data

---

## Switching Back to Growatt Cloud

If you need to restore cloud connectivity:

### Via AP Mode

1. Enable **AP Mode** on the charger. Best practice to do so is set up a TCP forwarder (see underneath), connect to charger via ShinePhone app (delete existing THOR and add again to regain acces)
2. Connect to the charger's Wi-Fi
3. Open the Growatt app
4. Restore the original server URL:
   ```
   ws://evcharge.growatt.com:80/ocpp/ws
   ```
5. Save and reboot

### Emergency Fallback: TCP Forwarder

If you're locked out and need temporary cloud access:

1. Install **Advanced SSH & Web Terminal** add-on in Home Assistant
2. Install `socat`:
   ```bash
   apk add socat
   ```
3. Run TCP forwarder:
   ```bash
   /usr/bin/socat TCP-LISTEN:9000,fork,reuseaddr TCP:evcharge.growatt.com:80
   ```
4. This forwards traffic from port 9000 to Growatt cloud
5. Charger will reconnect to cloud via Home Assistant
6. Use Growatt app to restore original server URL
7. Stop socat and restore this integration

⚠️ **Note**: If you get "address in use" errors, temporarily remove the integration and restart Home Assistant before running socat.

---

## Usage

### Entities Created

After successful connection, the integration creates the entities below. The listed entity IDs are the defaults generated from the current entity and device names. Existing installations and manually renamed entities may use different IDs.

#### Sensors

| Entity name | Default entity ID | Purpose |
|---|---|---|
| Status | `sensor.growatt_thor_ev_charger_status` | Charger status |
| Charge Point ID | `sensor.growatt_thor_ev_charger_charge_point_id` | Connected OCPP charge point ID |
| Charging Power | `sensor.growatt_thor_ev_charger_charging_power` | Total charging power (W) |
| Energy Charged | `sensor.growatt_thor_ev_charger_energy_charged` | Energy charged in the current session (kWh) |
| Total Energy Charged | `sensor.growatt_thor_ev_charger_total_energy_charged` | Persistent cumulative charging energy (kWh) |
| Current L1/L2/L3 | `sensor.growatt_thor_ev_charger_current_l1`<br>`sensor.growatt_thor_ev_charger_current_l2`<br>`sensor.growatt_thor_ev_charger_current_l3` | Charging current per phase (A) |
| Voltage L1/L2/L3 | `sensor.growatt_thor_ev_charger_voltage_l1`<br>`sensor.growatt_thor_ev_charger_voltage_l2`<br>`sensor.growatt_thor_ev_charger_voltage_l3` | Charger voltage per phase (V) |
| Power L1/L2/L3 | `sensor.growatt_thor_ev_charger_power_l1`<br>`sensor.growatt_thor_ev_charger_power_l2`<br>`sensor.growatt_thor_ev_charger_power_l3` | Charging power per phase (W) |
| Temperature | `sensor.growatt_thor_ev_charger_temperature` | Internal charger temperature (°C) |
| Grid power | `sensor.growatt_thor_external_meter_grid_power` | External meter power (W) |
| Grid voltage L1/L2/L3 | `sensor.growatt_thor_external_meter_grid_voltage_l1`<br>`sensor.growatt_thor_external_meter_grid_voltage_l2`<br>`sensor.growatt_thor_external_meter_grid_voltage_l3` | External meter voltage per phase (V) |
| Grid current L1/L2/L3 | `sensor.growatt_thor_external_meter_grid_current_l1`<br>`sensor.growatt_thor_external_meter_grid_current_l2`<br>`sensor.growatt_thor_external_meter_grid_current_l3` | External meter current per phase (A) |
| Server URL | `sensor.growatt_thor_ev_charger_server_url` | Configured OCPP endpoint |
| Working mode | `sensor.growatt_thor_ev_charger_working_mode` | Fast, PV Linkage, or Off-Peak operation |
| Authorization mode | `sensor.growatt_thor_ev_charger_authorization_mode` | Home Assistant/RFID, RFID only, or Plug & Charge authorization |
| Reported solar mode | `sensor.growatt_thor_ev_charger_solar_mode` | Disabled, PV Linkage with grid import, or solar-only PV Linkage+ read back from the charger |
| Reported PV Linkage grid import allowance | `sensor.growatt_thor_ev_charger_pv_linkage_grid_import_allowance` | Charger-normalized grid-import allowance for PV Linkage in kW |
| PV Linkage boost configuration | `sensor.growatt_thor_ev_charger_pv_linkage_boost_configuration` | Disabled, Manual, or Smart boost mode |
| Solar threshold current | `sensor.growatt_thor_ev_charger_solar_threshold_current` | Reported PV threshold current in A |
| Grid off-peak charging | `sensor.growatt_thor_ev_charger_grid_off_peak_charging` | Grid off-peak charging flag |
| Off-peak enable setting | `sensor.growatt_thor_ev_charger_off_peak_enable_setting` | Normalized off-peak mode state |
| Configured charging periods | `sensor.growatt_thor_ev_charger_off_peak_schedule` | Shared time windows used for Off-Peak charging or PV Linkage Manual Boost |
| Off-peak current | `sensor.growatt_thor_ev_charger_off_peak_current` | Reported off-peak charging current in A |
| Reported warm-up after full charge | `sensor.growatt_thor_ev_charger_warm_up_after_full_charge` | Warm-up state read back from the charger |
| Delayed charging time | `sensor.growatt_thor_ev_charger_delayed_charging_time` | Reported charger-side delay duration in seconds |
| Power meter type | `sensor.growatt_thor_external_meter_power_meter_type` | Configured external meter model |
| Power meter address | `sensor.growatt_thor_external_meter_power_meter_address` | Configured external Modbus address |
| External sampling method | `sensor.growatt_thor_external_meter_external_sampling_method` | External meter or current-transformer wiring method |
| Electricity Price | `sensor.growatt_thor_ev_charger_electricity_price` | Configured electricity price using the Home Assistant system currency per kWh |
| Last Session Energy | `sensor.growatt_thor_ev_charger_last_session_energy` | Energy from the most recently completed session |
| Last Session Cost | `sensor.growatt_thor_ev_charger_last_session_cost` | Cost from the most recently completed session using the Home Assistant system currency |
| Last Session Duration | `sensor.growatt_thor_ev_charger_last_session_duration` | Duration of the most recently completed session |
| Last Session Start | `sensor.growatt_thor_ev_charger_last_session_start` | Charging start timestamp |
| Last Session End | `sensor.growatt_thor_ev_charger_last_session_end` | Charging end timestamp |
| Last Session Plug Time | `sensor.growatt_thor_ev_charger_last_session_plug_time` | Cable connection timestamp |
| Last Session Unplug Time | `sensor.growatt_thor_ev_charger_last_session_unplug_time` | Cable disconnection timestamp |
| Last Session Transaction ID | `sensor.growatt_thor_ev_charger_last_session_transaction_id` | OCPP transaction ID for the last session |
| Last Session Charge Mode | `sensor.growatt_thor_ev_charger_last_session_charge_mode` | Translated Growatt authorization/charging mode for the last session; raw vendor code retained as an attribute |
| Last Session Work Mode | `sensor.growatt_thor_ev_charger_last_session_work_mode` | Translated Growatt operating mode when its vendor code is confirmed; raw code retained as an attribute |

External-meter measurements are polled in every charger working mode because
the same meter is used by load balancing and PV Linkage. A measurement remains
unavailable until the charger returns its field in `get_external_meterval`.

Warm-up support depends on the connected vehicle. The setting only allows a
compatible vehicle to continue drawing power after reaching full charge; it
does not directly control cabin or battery preconditioning.

The ShinePhone delayed-charging screen is inconsistent on the tested firmware:
both directions of its Random Delay switch wrote
`G_RandDelayChargeTime=0`. The integration therefore exposes only the reported
numeric delay and does not provide an unverified Random Delay control.

#### Controls

| Entity name | Type | Default entity ID | Purpose |
|---|---|---|---|
| Max Current | Number | `number.growatt_thor_ev_charger_max_current` | Maximum charging current (6-32 A) |
| Loadbalancing limit | Number | `number.growatt_thor_external_meter_loadbalancing_limit` | Grid import limit (kW) |
| Electricity Price | Number | `number.growatt_thor_ev_charger_electricity_price` | Electricity tariff using the Home Assistant system currency per kWh |
| Loadbalancing | Switch | `switch.growatt_thor_external_meter_loadbalancing` | Enable or disable dynamic load balancing |
| LCD Display | Switch | `switch.growatt_thor_ev_charger_lcd_display` | Enable or disable the charger display |
| Start charging | Button | `button.growatt_thor_ev_charger_start_charging` | Manually request a charging session |
| Stop charging | Button | `button.growatt_thor_ev_charger_stop_charging` | Stop the active charging session |
| Auto Charge Start Time | Time | `time.growatt_thor_ev_charger_auto_charge_start_time` | Schedule start time; changes auto-apply through the write queue |
| Auto Charge Stop Time | Time | `time.growatt_thor_ev_charger_auto_charge_stop_time` | Schedule stop time; changes auto-apply through the write queue |
| Charging strategy | Select | `select.growatt_thor_ev_charger_charging_strategy` | Select Fast, PV Linkage with grid import, solar-only PV Linkage+, or Off-Peak mode |
| PV Linkage grid import allowance | Number | `number.growatt_thor_ev_charger_pv_linkage_grid_import_allowance` | Grid power the charger may add in PV Linkage mode |
| Warm-up after full charge | Switch | `switch.growatt_thor_ev_charger_warm_up_after_full_charge` | Allow compatible vehicles to continue drawing power for preheating or defrosting |

Charger mode and AP mode are intentionally configured through **Settings → Devices & Services → Growatt THOR → Configure**. They are not select or button entities.

Control availability follows the effective mode reported by the charger:

| Control | Available in |
|---|---|
| Charging strategy | Any connected mode |
| Load balancing and its limit | Fast and Off-Peak |
| Automatic charging start/stop | Fast |
| PV Linkage grid import allowance | PV Linkage only; unavailable in solar-only PV Linkage+ |
| Warm-up after full charge | Any connected mode |

The charging-strategy select does not write `G_WorkingMode`; that key is a
readback of the effective mode. It uses the indirect writes captured from the
Growatt app: `G_SolarMode` selects Fast/PV Linkage variants and
`G_OffPeakEnable=1&Enable` selects Off-Peak. Home Assistant refreshes the
configuration after the charger has applied a change.

Growatt's naming is counterintuitive: PV Linkage allows the configured regular
grid import, while PV Linkage+ uses only solar surplus. Manual and Smart Boost
may still draw grid power in either PV variant.

Boost settings are staged locally and sent only after Apply is pressed. Manual
Boost requires its complete time window; Smart Boost requires both finish time
and target energy. The period readback is shared with Off-Peak mode, so the
integration always writes the complete applicable configuration instead of an
isolated partial value.

### Entity semantics

- Live measurements, session totals, and effective operating states are normal sensors.
- Values that can safely change charger behavior use `select`, `number`, `switch`, or `time` entities in the Configuration category.
- Retained vendor fields that are static, compound, or not safely writable are diagnostic sensors and keep their raw OCPP value as an attribute.
- Start and Stop are operational buttons rather than configuration entities.


## ⚡ Energy Dashboard

This integration is compatible with the Home Assistant Energy Dashboard.

### Setting up EV Charging tracking

1. Go to **Settings → Dashboards → Energy**
2. Scroll to **Individual device consumption**
3. Click **Add device**
4. Select `sensor.growatt_thor_ev_charger_energy_charged`

> **Note:** This sensor has `state_class: total_increasing`, meaning it resets to zero after each charging session. Home Assistant automatically detects these resets and accumulates all sessions correctly in the Energy Dashboard — including multiple sessions on the same day.

### Additional sensor (optional)

For real-time power monitoring on the Energy Dashboard:
- Use `sensor.growatt_thor_ev_charger_charging_power` for live wattage display

### Session history

For detailed per-session data (energy, cost, timestamps), check:
- the individual **Last Session** sensors on the Growatt THOR device
- `/config/growatt_thor_sessions.csv` for the complete session log
- the `growatt_thor.export_sessions` action for a date-filtered CSV export

The normalized values backing the **Last Session** sensors are stored in Home
Assistant and restored after a restart. Their record key is restored as well,
so a repeated `currentrecord` or `frozenrecord` is not counted twice.


### Example Automations

#### Start Charging When Solar Production is High

```yaml
automation:
  - alias: "Start EV charging with solar excess"
    trigger:
      - platform: numeric_state
        entity_id: sensor.solar_power
        above: 2000  # 2kW excess
    condition:
      - condition: state
        entity_id: sensor.growatt_thor_ev_charger_status
        state: "Idle"
    action:
      - service: button.press
        target:
          entity_id: button.growatt_thor_ev_charger_start_charging
```

#### Dynamic Load Balancing Based on Grid Import

```yaml
automation:
  - alias: "Adjust EV charging based on grid load"
    trigger:
      - platform: state
        entity_id: sensor.growatt_thor_load_balancing_grid_power
    action:
      - service: number.set_value
        target:
          entity_id: number.growatt_thor_load_balancing_loadbalancing_limit
        data:
          value: >
            {% set grid = states('sensor.growatt_thor_load_balancing_grid_power') | float %}
            {% set max_import = 10000 %}  {# 10kW max grid import #}
            {{ ((max_import - grid) / 1000) | round(0) | max(1) }}
```

---

## Issues
If you encounter issues, please report bugs. Do not forget to send logs with your bug report.
Enable debug logging in configuration.yaml

```yaml
logger:
  default: warning
  logs:
    custom_components.growatt_thor: debug
    ocpp: info
```

## Troubleshooting

### Charger Not Connecting

- **Check network connectivity**: Ping the charger from Home Assistant
- **Verify server URL**: Ensure correct IP address and port in Thor settings
- **Check firewall**: Port 9000 must be open
- **Check logs**: Settings → System → Logs → Filter by "growatt_thor" (enabled debug logging for this integration)
- **Restart charger**: Power cycle the Thor charger

### Polling Too Frequent / Too Slow

1. Go to **Settings → Devices & Services**
2. Click on **Growatt THOR** integration
3. Click **Configure**
4. Adjust **Grid Poll Interval**:
   - 30-60 seconds = recommended balance
   - 5-10 seconds = real-time (higher load)
   - 300-600 seconds = minimal load
5. Restart required after changes

### Thor Firmware Crash / Freezing

✅ **v1.1.0 includes major improvements to prevent crashes!**

This integration now includes enhanced anti-crash protection:
- **Write queue system**: All writes are queued with 20-second minimum interval
- **20-second polling pause** after each configuration change (increased from 10s)
- **Sequential execution**: Multiple rapid changes are buffered and executed safely
- **Smart polling**: Only when load balancing is active

If crashes still occur:
- Check logs for queued operations: `grep "Write queued" home-assistant.log`
- Increase poll interval to 60+ seconds
- Report issue with debug logs at [GitHub Issues]
- Check Thor firmware version

### Configuration Changes Not Applied

If configuration changes don't seem to work:
- Check logs for queue status: `grep "Waiting.*before next write" home-assistant.log`
- The write queue may be processing previous changes (20-second interval)
- Wait up to 20 seconds and check again
- UI updates immediately (optimistic), but actual write may be queued

---

## Technical Details

### OCPP Implementation

- **Protocol**: OCPP 1.6J (JSON over WebSocket)
- **Supported messages**:
  - BootNotification, Heartbeat, StatusNotification
  - StartTransaction, StopTransaction, MeterValues
  - Authorize, DataTransfer (Growatt vendor extensions)
  - RemoteStartTransaction, RemoteStopTransaction
  - GetConfiguration, ChangeConfiguration
  - TriggerMessage

### Growatt-Specific Features

- `G_MaxCurrent` - Maximum charging current
- `G_ExternalLimitPower` - Load balancing limit
- `G_ExternalLimitPowerEnable` - Load balancing toggle
- `G_ChargerMode` - Charging mode
- `G_AutoChargeTime` - Scheduled charging times
- `get_external_meterval` - Grid meter data request
- `frozenrecord` / `currentrecord` - Session history

The integration keeps the last-known raw and normalized values returned by
`GetConfiguration`. These values are included in the Home Assistant diagnostics
download. Network identifiers, credentials, and unregistered keys are redacted
in that export; sensitive credentials are also excluded from active requests.
The same diagnostics include the latest complete `MeterValues` payload and the
latest Growatt `currentrecord` and `frozenrecord`. Unknown meter measurands and
vendor fields are retained without automatically creating entities for them.
Raw Growatt session query strings and values of unknown session fields are
redacted in the downloaded diagnostics. A separate `sessions` section combines
matching OCPP and Growatt data without replacing either raw source. Its
correlation status distinguishes sessions reported by both sources from
OCPP-only and Growatt-only records, and energy differences remain visible.

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history and release notes.

---

## Contributing

Contributions are welcome! Please:
- Report bugs via [GitHub Issues](https://github.com/bobbesnl/growatt_thor/issues)
- Submit pull requests for improvements
- Share your experience and configurations

---

## Disclaimer

⚠️ **Use at your own risk**

- This software is provided AS-IS without warranty
- This is an unofficial integration not endorsed by Growatt
- Misconfiguration may:
  - Disable cloud access and Growatt app functionality
  - Interrupt charging operations
  - Require manual recovery via AP mode
  - In worst case: misconfiguration can cause fire when system is overloading! Be aware!
- The authors accept no responsibility for:
  - Damage to equipment or persons
  - Loss of functionality
  - Data loss or privacy issues
  - Electric vehicle charging issues

You are responsible for understanding the risks and ensuring safe operation.

---

## License

MIT License - see LICENSE file for details

---

## Support

- **Issues**: [GitHub Issues](https://github.com/bobbesnl/growatt_thor/issues)
- **Discussions**: [GitHub Discussions](https://github.com/bobbesnl/growatt_thor/discussions)
