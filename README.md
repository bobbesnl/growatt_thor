# Growatt THOR EV Charger – Home Assistant Integration (OCPP)

⚡ **Unofficial Home Assistant integration for the Growatt THOR EV charger**  
This project allows you to connect a Growatt THOR EV charger **directly to Home Assistant** using **OCPP 1.6 over WebSocket**, without relying on the Growatt cloud.

> ⚠️ This is an **unofficial community project**. Growatt is not affiliated in any way.

---

## What does this integration do?

This integration runs a **local OCPP server inside Home Assistant**.  
The Growatt THOR charger connects directly to Home Assistant instead of the Growatt backend.

Current goals:
- Receive charger status (Idle / Charging / Faulted)
- Receive live power and energy data
- Start / stop charging (planned)
- Configure charger behaviour (planned)
- Enable AP mode when needed (planned)

This approach avoids fragile MITM proxies and cloud dependencies.

---

## Architecture (high level)

Growatt THOR EV Charger
|
| OCPP 1.6 (WebSocket, unencrypted)
v
Home Assistant
└── Growatt THOR custom integration
└── Local OCPP server


The charger itself sends its **Charge Point ID automatically** as part of the WebSocket URL.

---

## Installation (via HACS)

### 1. Add the custom repository

1. Open **Home Assistant**
2. Go to **HACS → Integrations**
3. Click the **three dots (⋮)** → *Custom repositories*
4. Add:
   - **Repository**: `https://github.com/<your-github-username>/growatt_thor`
   - **Category**: Integration
5. Click **Add**
6. Search for **Growatt THOR EV Charger**
7. Install the integration
8. Restart Home Assistant

---

### 2. Add the integration

After restart:

1. Go to **Settings → Devices & Services**
2. Click **Add integration**
3. Search for **Growatt THOR**
4. Choose a listening port (default: `9000`)
5. Finish setup

Home Assistant is now waiting for the charger to connect.

---

## Configure the Growatt THOR charger

⚠️ **Important:**  
Changing the server URL may block access to the Growatt cloud and app.

In many cases (including mine), the **server URL can only be changed while the charger is in AP mode**.

### Typical steps (example)

1. Enable **AP Mode** on the Growatt THOR charger
2. Connect your phone to the charger's Wi-Fi access point
3. Open the **ShinePhone / Growatt app**
4. Go to charger network or server settings
5. Change the server URL to: ws://<HOME_ASSISTANT_IP>:9000/ocpp/ws

Example:
ws://192.168.1.101:9000/ocpp/ws


6. Save settings
7. Reboot the charger

If successful, Home Assistant will automatically detect the charger.

---

## Switching back to Growatt Cloud (important)

If something goes wrong and the charger no longer works as expected:

- You **must** restore the original Growatt server URL  
  (usually `ws://evcharge.growatt.com:80/ocpp/ws`)
- This often again requires **AP mode**

As a fallback, you can temporarily run a TCP forwarder (e.g. `socat`) on port 9000 to forward traffic back to Growatt.

---

## Disclaimer / Warning

⚠️ **Use at your own risk**

- This software is provided **as-is**
- There is **no warranty**
- Misconfiguration may:
  - Disable cloud access
  - Interrupt charging
  - Require manual recovery via AP mode
- The authors and contributors accept **no responsibility for damage, data loss, or malfunction**

You are responsible for understanding what you are doing.

---

## Status

🚧 **Work in progress**

This integration is under active development.  
Expect breaking changes, missing features, and rough edges.

Contributions, testing, and feedback are welcome.

---

## License

MIT License

