"""Live configuration projections captured before the dispatch-table refactor."""

import json
import unittest
from datetime import time
from math import isfinite
from pathlib import Path

from tests.support import build_coordinator

FIXTURE = Path(__file__).parent / "fixtures/configuration_projection_contract.json"
ATTRIBUTES = (
    "max_current",
    "external_limit_power",
    "external_limit_power_enable",
    "charger_mode",
    "server_url",
    "lcd_close_enable",
    "electricity_price",
    "auto_charge_start_time",
    "auto_charge_stop_time",
    "auto_charge_start_time_pending",
    "auto_charge_stop_time_pending",
)


def project(value):
    normalized = (
        str(value)
        if isinstance(value, time) or (isinstance(value, float) and not isfinite(value))
        else value
    )
    return {"type": type(value).__name__, "value": normalized}


def configuration_snapshots():
    coordinator = build_coordinator()
    coordinator.now = lambda: "2026-10-30T12:00:00Z"
    cases = (
        {
            "G_MaxCurrent": "16",
            "G_ExternalLimitPower": "4.5",
            "G_ExternalLimitPowerEnable": "1",
            "G_ChargerMode": "3",
            "G_ServerURL": "ws://example.invalid",
            "G_LCDCloseEnable": "1",
            "G_AutoChargeTime": "01:00-06:00",
            "G_TimeSharingPrice": "time1=00:00-23:59&price1=0.12345",
        },
        {"G_AutoChargeTime": "01:00-06:00"},
        {"G_AutoChargeTime": " 1:02 - 6:04 "},
        {"G_AutoChargeTime": "24:00-06:00"},
        {"G_AutoChargeTime": "01:00-99:00"},
        {"G_AutoChargeTime": ""},
        {"G_AutoChargeTime": None},
        {"G_AutoChargeTime": "no separator"},
        {"G_MaxCurrent": "invalid", "G_ExternalLimitPower": "NaN", "G_ChargerMode": "invalid"},
        {"G_TimeSharingPrice": "invalid"},
        {"G_TimeSharingPrice": "time1=00:00-23:59&price1=-0.054"},
        {"G_ExternalLimitPowerEnable": "True", "G_ServerURL": None, "G_LCDCloseEnable": None},
        {"G_ExternalLimitPowerEnable": "0", "G_AutoChargeTime": "00:00-23:59"},
        {"unknown_vendor_key": "unchanged"},
    )
    snapshots = []
    for values in cases:
        coordinator.process_configuration(
            [{"key": key, "value": value} for key, value in values.items()]
        )
        snapshots.append(
            {
                "values": {name: project(getattr(coordinator, name)) for name in ATTRIBUTES},
                "notifications": coordinator.updates,
            }
        )
    return snapshots


class ConfigurationProjectionContractTest(unittest.TestCase):
    def test_valid_invalid_missing_and_repeated_configuration_preserve_live_state(self):
        self.assertEqual(configuration_snapshots(), json.loads(FIXTURE.read_text()))
