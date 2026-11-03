"""Characterization snapshot of charger-state projections across OCPP states.

The status sensor, the live card fields and the PV dialog block reason all
derive a view from connection, OCPP status, transaction and the latest
MeterValues packet. This snapshot fixes their current outputs for a matrix of
charger states, so a change in how the state is read cannot alter them
unnoticed. Regenerate only for an intended behavior change:

    python -m tests.test_charger_state_contract --update
"""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests.support import build_coordinator, load_sensor_module

sensor = load_sensor_module()
card_data = sys.modules[f"{sensor.__package__}.presentation.card_data"]
CONTRACT = Path(__file__).parent / "fixtures/charger_state_contracts.json"
RECEIVED_AT = "2026-10-27T10:00:00Z"


def _packet(transaction_id, *samples, timestamp=RECEIVED_AT):
    return {
        "received_at": RECEIVED_AT,
        "connector_id": 1,
        "transaction_id": transaction_id,
        "meter_values": [{"timestamp": timestamp, "sampled_values": list(samples)}],
    }


def _sample(value, measurand="Power.Active.Import", phase=None, unit="W"):
    return {
        "measurand": measurand,
        "numeric_value": value,
        "raw_value": str(value),
        "phase": phase,
        "unit": unit,
    }


def _active(transaction_id):
    return {
        "start": {
            "received_at": "2026-10-27T09:00:00Z",
            "request": {"connector_id": 1, "timestamp": "2026-10-27T09:00:00Z"},
            "response": {"transaction_id": transaction_id},
        },
        "events": [],
    }


CHARGING_PACKET = _packet(
    7,
    _sample(7200),
    _sample(10.5, "Current.Import", "L1", "A"),
    _sample(10.4, "Current.Import", "L2", "A"),
    _sample(10.6, "Current.Import", "L3", "A"),
)
PHASE_POWER_PACKET = _packet(
    7,
    _sample(2400, phase="L1"),
    _sample(2.3, phase="L2", unit="kW"),
    _sample(2500, phase="L3"),
)

CASES = {
    "new_disconnected": {"connected": False},
    "connected_without_status": {},
    "available": {"status": "Available"},
    "preparing": {"status": "Preparing"},
    "charging": {
        "status": "Charging",
        "transaction_id": 7,
        "active_transaction": _active(7),
        "last_meter_values": CHARGING_PACKET,
    },
    "charging_phase_power_only": {
        "status": "Charging",
        "transaction_id": 7,
        "active_transaction": _active(7),
        "last_meter_values": PHASE_POWER_PACKET,
    },
    "charging_enum_status": {
        "status": SimpleNamespace(value="Charging"),
        "transaction_id": 7,
        "active_transaction": _active(7),
        "last_meter_values": CHARGING_PACKET,
    },
    "charging_socket_lost": {
        "connected": False,
        "status": "Charging",
        "transaction_id": 7,
        "active_transaction": _active(7),
        "last_meter_values": CHARGING_PACKET,
    },
    "suspended_ev": {
        "status": "SuspendedEV",
        "transaction_id": 7,
        "active_transaction": _active(7),
        "last_meter_values": CHARGING_PACKET,
    },
    "suspended_evse_restored": {"status": "SuspendedEVSE", "transaction_id": "7"},
    "finishing": {"status": "Finishing", "last_meter_values": CHARGING_PACKET},
    "faulted": {"status": "Faulted"},
    "faulted_during_transaction": {
        "status": "Faulted",
        "transaction_id": 7,
        "active_transaction": _active(7),
    },
    "reserved": {"status": "Reserved"},
    "unavailable": {"status": "Unavailable"},
    "idle_after_stop": {"status": "Idle"},
    "unknown_status": {"status": "Rebooting"},
}

CARD_FIELDS = (
    "transaction_active",
    "power_w",
    "currents_a",
    "sample_at",
    "meter_received_at",
    "meter_stale_after",
    "session_energy_kwh",
)


def coordinator(values):
    c = build_coordinator()
    c.hass.config = SimpleNamespace(currency="EUR", time_zone="Europe/Berlin")
    c.now = lambda: RECEIVED_AT
    c.connection_started_at = None
    c.last_message_at = None
    c.last_message_action = None
    c.last_heartbeat_at = None
    for name, value in values.items():
        setattr(c, name, value)
    return c


def status_entity(c):
    entity = object.__new__(sensor.StatusSensor)
    entity.coordinator = c
    entity.hass = c.hass
    return entity


def projection(values):
    c = coordinator(values)
    entity = status_entity(c)
    card = card_data.dashboard_attributes(c)
    return {
        "status_sensor": {"state": entity.native_value, "available": entity.available},
        "transaction_is_active": c.transaction_is_active,
        "charger_is_faulted": c.charger_is_faulted,
        "card": {name: card[name] for name in CARD_FIELDS},
        "pv_blocked_reason": card["pv_linkage"]["blocked_reason"],
    }


def snapshot():
    return {name: projection(values) for name, values in CASES.items()}


class ChargerStateContractTest(unittest.TestCase):
    def test_charger_state_projections_match_contract(self):
        self.assertEqual(snapshot(), json.loads(CONTRACT.read_text()))


if __name__ == "__main__":
    if "--update" in sys.argv:
        CONTRACT.write_text(json.dumps(snapshot(), indent=2, sort_keys=True) + "\n")
    else:
        unittest.main()
