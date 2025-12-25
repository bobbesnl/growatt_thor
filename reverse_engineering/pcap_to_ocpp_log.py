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

# tshark: pak ruwe TCP payload (werkt bij Growatt beter dan websocket dissector)
cmd = [
    "tshark",
    "-r", PCAP_FILE,
    "-Y", "tcp.port == 9000",
    "-T", "fields",
    "-e", "frame.time_epoch",
    "-e", "ip.src",
    "-e", "ip.dst",
    "-e", "tcp.payload"
]

proc = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    text=True
)

def try_parse_json_chunks(text):
    """
    Probeer meerdere JSON arrays uit één payload te vissen.
    """
    results = []
    idx = 0
    while True:
        start = text.find("[", idx)
        if start == -1:
            break
        try:
            obj, end = json.JSONDecoder().raw_decode(text[start:])
            results.append(obj)
            idx = start + end
        except Exception:
            idx = start + 1
    return results


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
            payload = bytes.fromhex(payload_hex.replace(":", "")).decode(
                "utf-8", errors="ignore"
            )
        except Exception:
            continue

        messages = try_parse_json_chunks(payload)
        if not messages:
            continue

        timestamp = datetime.fromtimestamp(float(ts)).isoformat()
        direction = f"{src} → {dst}"

        for msg in messages:
            if not isinstance(msg, list) or len(msg) < 3:
                continue

            msg_type = msg[0]
            msg_id = msg[1]
            action_or_payload = msg[2]

            out.write(f"\n[{timestamp}] {direction}\n")
            out.write(f"Raw messageTypeId: {msg_type}\n")

            # CALL
            if msg_type == 2:
                action = action_or_payload
                payload = msg[3] if len(msg) > 3 else {}
                out.write(f"OCPP CALL: {action}\n")

                if action == "DataTransfer":
                    vendor = payload.get("vendorId")
                    message_id = payload.get("messageId")
                    data = payload.get("data")
                    out.write(f"  Vendor: {vendor}\n")
                    out.write(f"  MessageId: {message_id}\n")
                    out.write("  Data:\n")
                    out.write(json.dumps(data, indent=2))
                else:
                    out.write("  Payload:\n")
                    out.write(json.dumps(payload, indent=2))

            # CALL RESULT
            elif msg_type == 3:
                out.write("OCPP RESPONSE\n")
                out.write(json.dumps(action_or_payload, indent=2))

            # CALL ERROR
            elif msg_type == 4:
                out.write("OCPP ERROR\n")
                out.write(json.dumps(msg, indent=2))

            else:
                out.write("UNKNOWN MESSAGE TYPE\n")
                out.write(json.dumps(msg, indent=2))

            out.write("\n")

print(f"OCPP log written to {OUTPUT_FILE}")

