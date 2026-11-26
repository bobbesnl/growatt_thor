"""Redacted diagnostics snapshots captured before splitting section builders."""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.support import build_coordinator, load_package_module

FIXTURE = Path(__file__).parent / "fixtures/diagnostics_contract.json"


async def diagnostic_snapshots():
    coordinator = build_coordinator()
    with patch.dict(
        sys.modules,
        {
            "homeassistant.config_entries": SimpleNamespace(ConfigEntry=object),
            "homeassistant.core": SimpleNamespace(HomeAssistant=object),
        },
    ):
        diagnostics = load_package_module("diagnostics")
    values = load_package_module("configuration.values")
    records = load_package_module("sessions.records")
    hass = coordinator.hass
    hass.config = SimpleNamespace(time_zone="UTC")
    hass.async_create_task = lambda coroutine: coroutine.close()
    coordinator.now = lambda: "2026-10-30T12:00:00Z"
    entry = SimpleNamespace(entry_id="diagnostics_test")
    snapshots = []

    async def capture():
        result = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
        snapshots.append(json.loads(json.dumps(result)))

    await capture()  # Unloaded entries deliberately have a smaller shape.
    hass.data["growatt_thor"][entry.entry_id] = {
        "config_entry_id": entry.entry_id,
        "coordinator": coordinator,
    }
    await capture()
    coordinator.configuration_values = {
        key: values.configuration_value_from_item({"key": key, "value": value})
        for key, value in {
            "G_MaxCurrent": "16",
            "G_ChargerNetIP": "192.0.2.42",
            "FutureKey": "secret",
        }.items()
    }
    coordinator.unknown_configuration_keys = ("FutureKey",)
    coordinator.sessions.start_transaction(42, "PRIVATE-RFID", connector_id=1, meter_start=1000)
    coordinator.ingest.observe_meter_values(
        [
            {
                "timestamp": coordinator.now(),
                "sampled_value": [
                    {"value": "1500", "measurand": "Energy.Active.Import.Register", "unit": "Wh"},
                    {"value": "3000", "measurand": "Power.Active.Import", "unit": "W"},
                ],
            }
        ],
        transaction_id=42,
        connector_id=1,
    )
    await capture()
    coordinator.now = lambda: "2026-10-30T12:02:00Z"
    coordinator.sessions.stop_transaction(transaction_id=42, meter_stop=1500, reason="Remote")
    coordinator.sessions.process_session_record(
        records.parse_growatt_session_record(
            "currentrecord",
            "transactionId=42&starttime=2026-10-30 12:00:00&endtime=2026-10-30 12:02:00&"
            "costenergy=500&costmoney=12&chargemode=3&workmode=3",
        )
    )
    await capture()
    return snapshots


class DiagnosticsContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_unloaded_empty_active_and_completed_diagnostics(self):
        expected = json.loads(FIXTURE.read_text())
        actual = await diagnostic_snapshots()
        self.assertEqual(actual, expected)
        serialized = json.dumps(actual)
        self.assertNotIn("PRIVATE-RFID", serialized)
        self.assertNotIn("192.0.2.42", serialized)
        self.assertNotIn('"secret"', serialized)
