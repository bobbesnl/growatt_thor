# Growatt THOR EV Charger – Home Assistant Integration

⚡ **Unofficial Home Assistant integration for the Growatt THOR EV charger**  

This integration allows you to connect a Growatt THOR EV charger **directly to Home Assistant** using **OCPP 1.6 over WebSocket**, providing local control without relying on the Growatt cloud.

> ⚠️ This is an **unofficial community project**. Growatt is not affiliated with or endorsing this integration in any way.

---

## Features

### 📊 Real-time Monitoring
- **Charger status**: Idle, Preparing, Charging, Finishing, Faulted, Unavailable
- **Power monitoring**: Total power and per-phase (L1, L2, L3) in Watts
- **Current monitoring**: Current draw per phase in Amperes
- **Voltage monitoring**: Voltage per phase
- **Energy tracking**: Session energy in kWh with automatic reset per session
- **Temperature**: Internal charger temperature in °C
- **Transaction tracking**: Active transaction ID and charging session details (saved in sensor.growatt_thor_ev_charger_last_sessions)

### 🔌 Grid & Load Balancing
- **External meter monitoring**: Real-time grid power, voltage, and current per phase
- **Dynamic load balancing**: Set maximum grid import limit (kW) to prevent overload
- **Smart polling**: Configurable polling interval (5-3600 sec. recommended setting 30 seconds)
  - ⚠️ **Note**: Polling interval only affects the frequency of grid data **display updates** in Home Assistant. Load balancing functionality itself operates independently and responds in real-time regardless of the polling setting.
- **Wiring detection**: Automatic 1-phase or 3-phase detection

### ⚙️ Configuration & Control
- **Max current control**: Set maximum charging current (6-32A)
- **Charging schedule**: Configure automatic start/stop times
- **Charger modes**: Switch between Plug & Charge, RFID only, APP/RFID modes
- **Manual charging control**: Start and stop charging sessions via buttons
- **Load balancing toggle**: Enable/disable dynamic load balancing
- **Auto update THOR time**: Auto sync time with server time at every heartbeat and with reboot (ocpp protocol)

### 📈 Session History
- **Last 5 sessions**: Energy (kWh), cost, charge mode, work mode, timestamps
- **Current session tracking**: Real-time updates during active charging

### 🛡️ Stability Features
- **Anti-crash protection**: Automatic polling pause after configuration changes to prevent Thor firmware crashes
- **TIER 2 error recovery**: Robust error handling for connection issues
- **Smart polling**: Only polls external meter when load balancing is enabled

---

### Future Features (wishlist)
- Enabling solar powered EV charging
- RFID card management
- Enabling AP mode from within integration
- Enabling data passthrough to Growatt cloud server
- Other...?

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

1. **Add custom repository**
   - Open **Home Assistant**
   - Go to **HACS → Integrations**
   - Click **⋮** (three dots) → **Custom repositories**
   - Add repository:
     - **URL**: `https://github.com/bobbesnl/growatt_thor`
     - **Category**: `Integration`
   - Click **Add**

2. **Install the integration**
   - Search for **Growatt THOR EV Charger** in HACS
   - Click **Download**
   - Restart Home Assistant

3. **Configure the integration**
   - Go to **Settings → Devices & Services**
   - Click **+ Add Integration**
   - Search for **Growatt THOR**
   - Configure:
     - **Listen IP**: `0.0.0.0` (default, listens on all interfaces)
     - **Listen Port**: `9000` (default, or choose your own)
     - **Grid Poll Interval**: `30` seconds (recommended)
       - Range: 5-3600 seconds
       - Lower values = more frequent updates (higher load on Thor)
       - Higher values = less frequent updates (lower load)
       - **Important**: This only affects display update frequency, not load balancing functionality
   - Click **Submit**

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

1. **Enable AP Mode** on the Growatt THOR charger (via Shinephone app)
2. Connect your phone to the THOR's Wi-Fi (Standard Wi-Fi password is `12345678`)
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

After successful connection, the following entities are created:

#### Sensors
- `sensor.growatt_thor_status` - Charger status
- `sensor.growatt_thor_power` - Total charging power (W)
- `sensor.growatt_thor_energy` - Session energy (kWh)
- `sensor.growatt_thor_current_l1/l2/l3` - Current per phase (A)
- `sensor.growatt_thor_voltage_l1/l2/l3` - Voltage per phase (V)
- `sensor.growatt_thor_power_l1/l2/l3` - Power per phase (W)
- `sensor.growatt_thor_temperature` - Internal temperature (°C)
- `sensor.growatt_thor_grid_power` - Grid connection power (W)
- `sensor.growatt_thor_transaction_id` - Active transaction ID
- `sensor.growatt_thor_last_session_energy` - Previous session energy
- `sensor.growatt_thor_last_session_cost` - Previous session cost
- `sensor.growatt_thor_ev_charger_last_sessions` - Session tracking (only last 5 sessions)

#### Controls
- `number.growatt_thor_max_current` - Maximum charging current (6-32A)
- `number.growatt_thor_load_balancing_limit` - Grid import limit (kW)
- `switch.growatt_thor_load_balancing` - Enable/disable load balancing
- `select.growatt_thor_charger_mode` - Charging mode (Smart/Fast/ECO)
- `time.growatt_thor_charging_start` - Auto-charge start time
- `time.growatt_thor_charging_stop` - Auto-charge stop time
- `button.growatt_thor_start_charging` - Manual start
- `button.growatt_thor_stop_charging` - Manual stop
- `button.growatt_thor_apply_schedule` - Apply time schedule changes

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
        entity_id: sensor.growatt_thor_status
        state: "Idle"
    action:
      - service: button.press
        target:
          entity_id: button.growatt_thor_start_charging
```

#### Sync THOR time after DST change

```yaml
automation:
  - alias: "Sync Thor time after DST change"
    trigger:
      - platform: time
        at: "03:00:00"
    condition:
      - condition: template
        value_template: >
          {{ now().month in [3, 10] and now().day <= 7 and now().weekday() == 6 }}
    action:
      - service: growatt_thor.sync_time
```

---

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

This integration includes anti-crash protection:
- Automatic 10-second polling pause after configuration changes
- Automatic 5-second pause after start/stop commands
- Smart polling (only when load balancing is active)

If crashes persist:
- Collect debug logging and open an issue at my github repo
- Increase poll interval to 60+ seconds
- Disable load balancing temporarily
- Check Thor firmware version (updates may improve stability)

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
- `G_ChargerMode` - Charging mode (0=Smart, 1=Fast, 2=ECO)
- `G_AutoChargeTime` - Scheduled charging times
- `get_external_meterval` - Grid meter data request
- `frozenrecord` / `currentrecord` - Session history

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

