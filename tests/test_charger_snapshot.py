"""The charger snapshot derives state without changing its observations."""

import dataclasses
import unittest
from types import SimpleNamespace

from tests.support import load_package_module

snapshot_module = load_package_module("charging.snapshot")
VehicleState = snapshot_module.VehicleState

PACKET = {
    "received_at": "2026-10-27T10:00:05Z",
    "transaction_id": 7,
    "meter_values": [
        {
            "timestamp": "2026-10-27T09:59:00Z",
            "sampled_values": [{"measurand": "Power.Active.Import", "numeric_value": 1000}],
        },
        {
            "timestamp": "2026-10-27T10:00:00Z",
            "sampled_values": [
                {"measurand": "Power.Active.Import", "numeric_value": 7200, "unit": "W"},
                {"measurand": "Current.Import", "numeric_value": 10.5, "phase": "L1"},
                {"measurand": "Current.Import", "numeric_value": 10.4, "phase": "L2"},
            ],
        },
    ],
}


def owner(**values):
    defaults = {
        "connected": True,
        "status": None,
        "transaction_id": None,
        "transaction_is_active": False,
        "last_meter_values": None,
        "effective_meter_gap_seconds": 180.0,
    }
    return SimpleNamespace(**(defaults | values))


def snapshot(**values):
    return snapshot_module.charger_snapshot(owner(**values))


class ChargerSnapshotTest(unittest.TestCase):
    def test_vehicle_state_follows_iec_61851_style_groups(self):
        for status, expected in (
            ("Available", VehicleState.DISCONNECTED),
            ("Preparing", VehicleState.CONNECTED),
            ("SuspendedEV", VehicleState.CONNECTED),
            ("SuspendedEVSE", VehicleState.CONNECTED),
            ("Finishing", VehicleState.CONNECTED),
            ("Charging", VehicleState.CHARGING),
            ("Faulted", VehicleState.FAULT),
            ("Reserved", VehicleState.UNKNOWN),
            ("Unavailable", VehicleState.UNKNOWN),
            ("Idle", VehicleState.UNKNOWN),
            ("Rebooting", VehicleState.UNKNOWN),
            (None, VehicleState.UNKNOWN),
        ):
            with self.subTest(status=status):
                self.assertIs(snapshot(status=status).vehicle_state, expected)

    def test_lost_connection_makes_the_vehicle_state_unknown(self):
        value = snapshot(connected=False, status="Charging")
        self.assertIs(value.vehicle_state, VehicleState.UNKNOWN)
        # The last OCPP status stays visible as a raw and normalized value.
        self.assertEqual((value.ocpp_status, value.status), ("Charging", "charging"))

    def test_enum_status_keeps_its_wire_value(self):
        value = snapshot(status=SimpleNamespace(value="SuspendedEV"))
        self.assertEqual((value.ocpp_status, value.status), ("SuspendedEV", "suspended_ev"))
        self.assertFalse(value.faulted)
        self.assertTrue(snapshot(status="Faulted").faulted)

    def test_meter_reading_uses_only_the_latest_entry_and_keeps_its_times(self):
        meter = snapshot(last_meter_values=PACKET).meter
        self.assertEqual(meter.transaction_id, 7)
        self.assertEqual(meter.received_at, "2026-10-27T10:00:05Z")
        self.assertEqual(meter.sample_at, "2026-10-27T10:00:00Z")
        self.assertEqual(meter.power_w, 7200)
        self.assertEqual(meter.currents_a, (10.5, 10.4, None))
        self.assertEqual(snapshot().meter, snapshot_module.MeterReading())

    def test_live_meter_zeroes_display_but_keeps_the_raw_reading(self):
        charging = snapshot(status="Charging", last_meter_values=PACKET)
        self.assertIs(charging.live_meter(), charging.meter)
        self.assertEqual(snapshot(last_meter_values=PACKET).live_meter().power_w, 7200)
        for values in ({"status": "SuspendedEV"}, {"status": "Charging", "connected": False}):
            with self.subTest(**values):
                value = snapshot(last_meter_values=PACKET, **values)
                live = value.live_meter()
                self.assertEqual((live.power_w, live.currents_a), (0, (0, 0, 0)))
                self.assertEqual(live.sample_at, value.meter.sample_at)
                self.assertEqual(value.meter.power_w, 7200)

    def test_snapshot_is_immutable_and_reads_transaction_and_gap_from_owner(self):
        value = snapshot(transaction_id="7", transaction_is_active=True)
        self.assertEqual((value.transaction_id, value.transaction_active), ("7", True))
        self.assertEqual(value.meter_stale_after_s, 180.0)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            value.connected = False

    def test_wire_observation_matches_the_card_format(self):
        meter = snapshot(last_meter_values=PACKET).meter
        self.assertEqual(
            meter.as_observation(),
            {"power_w": 7200, "currents_a": [10.5, 10.4, None], "sample_at": meter.sample_at},
        )


if __name__ == "__main__":
    unittest.main()
