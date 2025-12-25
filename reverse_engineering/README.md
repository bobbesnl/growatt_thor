# Growatt THOR OCPP – Logging, Analyse & Reverse Engineering

Dit document beschrijft **hoe we het OCPP-verkeer van de Growatt THOR EV-lader hebben gelogd**, **hoe we de data hebben geëxtraheerd**, en **welke OCPP-berichten er écht toe doen** om een werkende Home Assistant‑integratie te bouwen.

Het doel is nadrukkelijk **begrip en reproduceerbaarheid**, niet alleen een werkende hack.

---

## 1. Architectuur-overzicht

### 1.1 Normale situatie

```
Growatt THOR  →  Growatt Cloud OCPP Server
```

- Communicatie via **OCPP 1.6 over WebSocket**
- Growatt gebruikt **standaard OCPP-berichten**, maar met **vendor-specifieke semantiek**

---

### 1.2 Onze observatie-opstelling

```
Growatt THOR
     │
     ▼
[socat proxy :9000]  →  evcharge.growatt.com:80
     │
     ▼
[tcpdump / pcap]
```

Hiermee:
- blijven **alle functies van de lader intact**
- kunnen we **passief observeren**
- krijgen we **exact hetzelfde verkeer** dat Growatt ziet

---

## 2. Logging-infrastructuur

### 2.1 socat – OCPP proxy (observer mode)

**Doel:** transparant doorsturen van OCPP-verkeer terwijl we meeluisteren.

#### systemd service: `thor-ocpp-socat.service`

```ini
[Unit]
Description=THOR OCPP socat proxy (observer mode)
After=network.target

[Service]
ExecStart=/usr/bin/socat \
  TCP-LISTEN:9000,fork,reuseaddr \
  TCP:evcharge.growatt.com:80
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

**Belangrijk:**
- De THOR wordt geconfigureerd om te verbinden met `server-ip:9000`
- socat forwardt alles 1:1 naar Growatt

---

### 2.2 tcpdump – ruwe packet capture

**Doel:** volledige TCP/WebSocket payload bewaren voor latere analyse.

#### systemd service: `thor-ocpp-tcpdump.service`

```ini
[Unit]
Description=THOR OCPP raw traffic logger (pcap)
After=network.target thor-ocpp-socat.service
Requires=thor-ocpp-socat.service

[Service]
ExecStart=/usr/bin/tcpdump \
  -i any \
  -s 0 \
  -w /var/log/thor-ocpp/raw/ocpp-%Y-%m-%d.pcap \
  -G 86400 \
  -W 7 \
  tcp port 9000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Resultaat:
- Dagelijkse `.pcap` bestanden
- Ruwe waarheid, onafhankelijk van tooling

---

## 3. Waarom tshark alleen niet genoeg was

### 3.1 Probleem

- OCPP draait over **WebSocket**
- WebSocket payloads zijn:
  - gemaskeerd
  - gefragmenteerd
  - TCP-gesegmenteerd

Daardoor gaven simpele tshark-commando’s:
- lege output
- of alleen ping/pong frames

---

## 4. OCPP extractie via Python (succesvolle aanpak)

### 4.1 Strategie

1. Extract **tcp.payload** (hex)
2. Decodeer naar UTF‑8
3. Zoek JSON-arrays (`[2,…]`, `[3,…]`)
4. Parse OCPP-structuur

---

### 4.2 Python script – OCPP decoder

Dit script:
- werkt robuust met WebSocket over TCP
- reconstrueert OCPP Calls & Responses
- schrijft leesbare logs

*(gebruik exact dit script – bewezen werkend)*

```python
#!/usr/bin/env python3

import subprocess
import json
import sys
import os
from datetime import datetime

if len(sys.argv) < 2:
    print("Usage: pcap_to_ocpp_log.py <file.pcap>")
    sys.exit(1)

PCAP_FILE = sys.argv[1]
WS_DIR = "/var/log/thor-ocpp/ws"
os.makedirs(WS_DIR, exist_ok=True)

base = os.path.basename(PCAP_FILE).replace(".pcap", "")
OUTPUT_FILE = os.path.join(WS_DIR, f"{base}.ocpp.log")

cmd = [
    "tshark",
    "-r", PCAP_FILE,
    "-Y", "tcp.port == 9000",
    "-T", "fields",
    "-e", "frame.time_epoch",
    "-e", "ip.src",
    "-e", "ip.dst",
    "-e", "tcp.payload",
]

proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

with open(OUTPUT_FILE, "w") as out:
    out.write(f"# OCPP log generated from {PCAP_FILE}\n")
    out.write("# ==================================================\n\n")

    for line in proc.stdout:
        parts = line.strip().split("\t")
        if len(parts) < 4:
            continue

        ts, src, dst, payload_hex = parts
        if not payload_hex:
            continue

        try:
            payload = bytes.fromhex(payload_hex.replace(":", "")).decode("utf-8", errors="ignore")
        except Exception:
            continue

        for candidate in payload.split("["):
            candidate = "[" + candidate
            try:
                data = json.loads(candidate)
            except Exception:
                continue

            if not isinstance(data, list) or len(data) < 3:
                continue

            timestamp = datetime.fromtimestamp(float(ts)).isoformat()
            msg_type = data[0]
            message_id = data[1]

            out.write(f"\n[{timestamp}] {src} → {dst}\n")
            out.write(f"Raw messageTypeId: {msg_type}\n")

            if msg_type == 2:
                out.write(f"OCPP CALL: {data[2]}\n")
                if len(data) > 3:
                    out.write("  Payload:\n")
                    out.write(json.dumps(data[3], indent=2))
            elif msg_type == 3:
                out.write("OCPP RESPONSE\n")
                out.write(json.dumps(data[2], indent=2))

            out.write("\n")

print(f"OCPP log written to {OUTPUT_FILE}")
```

---

## 5. Cruciale observaties uit de OCPP logs

### 5.1 Wat Growatt **niet** doet

- ❌ Geen `MeterValues`
- ❌ Geen spontane meetdata
- ❌ Geen standaard OCPP energy flow

---

### 5.2 Wat Growatt **wel** doet (belangrijk!)

#### 🔑 DataTransfer – sleutelmechanisme

```text
OCPP CALL: DataTransfer
MessageId: get_external_meterval
Data: null
```

➡️ **Hiermee vraagt de server actief meetdata op**

Dit gebeurt:
- periodiek
- bij start/stop transactie
- na StatusNotification

---

#### 🔧 ChangeConfiguration = beleidssturing

Voorbeelden:
- `G_SolarBoost`
- `G_PeriodTime`
- `G_OffPeakEnable`
- `G_ExternalSamplingCurWring`

➡️ Zonder deze instellingen blijft de lader grotendeels stil.

---

## 6. Gevolgen voor Home Assistant integratie

### 6.1 Waarom alleen status werkt

- `StatusNotification` is standaard OCPP
- die accepteert de THOR altijd

### 6.2 Waarom power / current / energy leeg blijven

- Growatt gebruikt **geen MeterValues**
- Meetdata komt alleen na:

```text
DataTransfer (get_external_meterval)
```

➡️ HA moet zich **gedragen als Growatt-server**

---

## 7. Wat nu nodig is voor een werkende integratie

1. **DataTransfer polling implementeren**
2. `get_external_meterval` actief sturen
3. Handshake‑sleutel (`12345678`) gebruiken
4. Responses parsen → sensoren vullen
5. ChangeConfiguration bij connect toepassen

---

## 8. Samenvatting

- Growatt gebruikt OCPP **transport**, maar eigen **datamodel**
- Reverse engineering via socat + tcpdump is betrouwbaar
- Python-decoder is cruciaal (tshark alleen is onvoldoende)
- De sleutel tot meetdata is `DataTransfer(get_external_meterval)`

➡️ Met deze kennis is een **volledig functionele HA-integratie realistisch en haalbaar**.

---

*Document opgesteld op basis van praktijkanalyse, pcap-onderzoek en live tests met Growatt THOR EV Charger.*

