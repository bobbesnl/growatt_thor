"""Storage snapshots captured before moving session state out of the coordinator."""

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests.support import MemoryStore, build_coordinator, load_package_module

FIXTURE = Path(__file__).parent / "fixtures/session_storage_contract.json"


async def session_snapshots():
    records = load_package_module("sessions.records")
    clock = ["2026-10-30T12:00:00Z"]
    coordinator = build_coordinator()
    coordinator.hass.config = SimpleNamespace(time_zone="UTC")
    coordinator.hass.async_create_task = lambda coroutine: coroutine.close()
    coordinator.now = lambda: clock[0]
    coordinator.runtime_data["append_session_to_csv"] = object()
    snapshots = []

    def capture():
        snapshots.append(json.loads(json.dumps(coordinator._storage_data())))

    coordinator.record_status_notification(1, "Preparing", "NoError")
    coordinator.start_transaction(42, "TEST-TAG", connector_id=1, meter_start=1000)
    capture()
    clock[0] = "2026-10-30T12:01:00Z"
    coordinator.process_meter_values(
        [
            {
                "timestamp": clock[0],
                "sampled_value": [
                    {"value": "1500", "measurand": "Energy.Active.Import.Register", "unit": "Wh"},
                    {"value": "3000", "measurand": "Power.Active.Import", "unit": "W"},
                ],
            }
        ],
        transaction_id=42,
        connector_id=1,
    )
    capture()
    clock[0] = "2026-10-30T12:02:00Z"
    coordinator.record_status_notification(1, "SuspendedEV", "NoError")
    capture()
    coordinator.stop_transaction(transaction_id=42, meter_stop=1500, reason="Remote")
    capture()
    payload = (
        "transactionId=42&starttime=2026-10-30 12:00:00&endtime=2026-10-30 12:02:00&"
        "plugtime=2026-10-30 12:00:00&costenergy=500&costmoney=12&chargemode=3&workmode=3"
    )
    coordinator.process_session_record(
        records.parse_growatt_session_record("currentrecord", payload)
    )
    capture()
    coordinator.process_session_record(
        records.parse_growatt_session_record("frozenrecord", payload)
    )
    capture()
    restored = build_coordinator(store=MemoryStore(snapshots[-1]))
    restored.hass.config = coordinator.hass.config
    restored.hass.async_create_task = coordinator.hass.async_create_task
    restored.now = coordinator.now
    await restored.async_load_storage()
    snapshots.append(json.loads(json.dumps(restored._storage_data())))
    return snapshots


class SessionStorageContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_start_meter_pause_stop_vendor_duplicate_and_restore_preserve_storage(self):
        expected = json.loads(FIXTURE.read_text())
        self.assertEqual(await session_snapshots(), expected)
