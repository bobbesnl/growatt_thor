"""Storage snapshots captured before moving session state out of the coordinator."""

import json
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
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

    coordinator.ingest.observe_status_notification(1, "Preparing", "NoError")
    coordinator.sessions.start_transaction(42, "TEST-TAG", connector_id=1, meter_start=1000)
    capture()
    clock[0] = "2026-10-30T12:01:00Z"
    coordinator.ingest.observe_meter_values(
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
    coordinator.ingest.observe_status_notification(1, "SuspendedEV", "NoError")
    capture()
    coordinator.sessions.stop_transaction(transaction_id=42, meter_stop=1500, reason="Remote")
    capture()
    payload = (
        "transactionId=42&starttime=2026-10-30 12:00:00&endtime=2026-10-30 12:02:00&"
        "plugtime=2026-10-30 12:00:00&costenergy=500&costmoney=12&chargemode=3&workmode=3"
    )
    coordinator.sessions.process_session_record(
        records.parse_growatt_session_record("currentrecord", payload)
    )
    capture()
    coordinator.sessions.process_session_record(
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

    async def test_goal_survives_active_restore_and_late_vendor_delivery(self):
        records = load_package_module("sessions.records")
        history = load_package_module("sessions.history_views")
        csv = load_package_module("sessions.csv")
        card = load_package_module("presentation.card_data")
        day = date.today().isoformat()
        clock = [f"{day}T12:00:00Z"]

        async def restore(checkpoint=None):
            coordinator = build_coordinator(store=MemoryStore(checkpoint or {}))
            coordinator.hass.config = SimpleNamespace(time_zone="UTC")
            coordinator.hass.async_create_task = lambda coroutine: coroutine.close()
            coordinator.now = lambda: clock[0]
            coordinator.runtime_data["append_session_to_csv"] = object()
            await coordinator.async_load_storage()
            return coordinator

        coordinator = await restore()
        goal = {"kind": "energy", "value": 5.0}

        async def observed(**_kwargs):
            pass

        coordinator.transaction_hooks = SimpleNamespace(
            session_goal_for_start=lambda: goal,
            transaction_started=observed,
            transaction_stopped=observed,
        )
        coordinator.sessions.start_transaction(42, connector_id=1, meter_start=1000)
        coordinator.energy = 1200
        coordinator = await restore(coordinator._storage_data())
        self.assertEqual(
            card.dashboard_active_session(coordinator)["charging_goal"],
            {**goal, "actual": 1.2},
        )

        clock[0] = f"{day}T12:20:00Z"
        coordinator.sessions.stop_transaction(transaction_id=42, meter_stop=3350, reason="Remote")
        coordinator = await restore(coordinator._storage_data())
        for transaction_id in (43, 42):
            payload = (
                f"transactionId={transaction_id}&starttime={day} 12:00:00&endtime={day} 12:20:00&"
                f"plugtime={day} 12:00:00&costenergy=2350&costmoney=50&chargemode=3&workmode=0"
            )
            coordinator.sessions.process_session_record(
                records.parse_growatt_session_record("frozenrecord", payload)
            )
        with TemporaryDirectory() as folder:
            path = Path(folder) / "sessions.csv"
            rows = coordinator.sessions.outbox.snapshot()
            self.assertEqual(len(rows), 2)
            for row in rows:
                csv.append_session_row(path, row)
            reported = {
                row["session_id"]: row for row in history.dashboard_session_data(path)["items"]
            }
            self.assertNotIn("charging_goal", reported[rows[0]["session_id"]])
            self.assertEqual(
                reported[rows[1]["session_id"]]["charging_goal"], {**goal, "actual": 2.35}
            )
            self.assertEqual(
                history.session_detail_data(path, rows[1]["session_id"])["charging_goal"],
                {**goal, "actual": 2.35},
            )
