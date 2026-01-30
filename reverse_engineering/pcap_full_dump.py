#!/usr/bin/env python3
"""Dump ALLE TCP payloads uit PCAP, ook niet-JSON data."""

import subprocess
import sys
import os
from datetime import datetime

if len(sys.argv) < 2:
    print("Usage: pcap_full_dump.py <file.pcap>")
    sys.exit(1)

PCAP_FILE = sys.argv[1]
OUTPUT_FILE = PCAP_FILE.replace(".pcap", ".full-dump.txt")

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

print(f"🔍 Analyzing {PCAP_FILE}...")
print(f"📝 Output: {OUTPUT_FILE}")

proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

with open(OUTPUT_FILE, "w") as out:
    out.write(f"# FULL TCP DUMP from {PCAP_FILE}\n")
    out.write("# ==================================================\n\n")

    packet_count = 0
    interesting_count = 0

    for line in proc.stdout:
        parts = line.strip().split("\t")
        if len(parts) < 4:
            continue

        ts, src, dst, payload_hex = parts
        if not payload_hex:
            continue

        try:
            payload = bytes.fromhex(payload_hex.replace(":", "")).decode("utf-8", errors="replace")
        except Exception:
            continue

        packet_count += 1
        timestamp = datetime.fromtimestamp(float(ts)).isoformat()
        direction = f"{src} → {dst}"

        # Check of het interessant is
        interesting_keywords = [
            "AP", "ap_mode", "apmode", "wifi", "Wifi", "WIFI",
            "network", "Network", "mode", "Mode",
            "config", "Config", "ChangeConfiguration",
            "G_NetworkMode", "G_APMode", "G_WifiMode"
        ]
        is_interesting = any(kw in payload for kw in interesting_keywords)

        if is_interesting:
            interesting_count += 1
            out.write(f"\n{'='*70}\n")
            out.write(f"⚠️  INTERESTING PACKET #{interesting_count}\n")
            out.write(f"{'='*70}\n")

        out.write(f"\n[{timestamp}] {direction}\n")
        out.write(f"Payload (length={len(payload)}):\n")
        out.write("-" * 70 + "\n")
        out.write(payload)
        out.write("\n" + "-" * 70 + "\n")

        # Extra: zoek naar JSON-achtige structuren
        if "[" in payload or "{" in payload:
            out.write("💡 Contains JSON-like structure\n")

print(f"\n✅ Processed {packet_count} packets")
print(f"⚠️  Found {interesting_count} interesting packets")
print(f"📄 Check: {OUTPUT_FILE}")
