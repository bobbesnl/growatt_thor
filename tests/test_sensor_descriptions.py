"""Characterization snapshots protect public sensor contracts during table refactors."""

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests.support import build_coordinator, load_sensor_module

sensor = load_sensor_module()
CONTRACT = Path(__file__).parent / "fixtures/sensor_contracts.json"
SIMPLE = (
    "ServerUrlSensor",
    "ChargePointIdSensor",
    "ChargingPowerSensor",
    "EnergyChargedSensor",
    "TotalEnergyChargedSensor",
    "ElectricityPriceSensor",
    "LastSessionEnergySensor",
    "LastSessionCostSensor",
    "LastSessionDurationSensor",
    "LastSessionEffectiveChargingDurationSensor",
    "LastSessionStartSensor",
    "LastSessionEndSensor",
    "LastSessionPlugTimeSensor",
    "LastSessionUnplugTimeSensor",
    "LastSessionTransactionIdSensor",
    "LastSessionChargeModeSensor",
    "LastSessionWorkModeSensor",
    "TemperatureSensor",
    "ExternalMeterHealthSensor",
    "GridPowerSensor",
)
PHASED = (
    "CurrentSensor",
    "VoltageSensor",
    "PhasePowerSensor",
    "GridVoltageSensor",
    "GridCurrentSensor",
)


def coordinator(case):
    c = build_coordinator()
    c.hass.config = SimpleNamespace(currency="EUR", time_zone="Europe/Berlin")
    c.now = lambda: "2026-10-27T10:00:00Z"
    c.last_update_success = case != "coordinator_failed"
    c.connected = case != "disconnected"
    if case == "unknown":
        c.charge_point_id = None
    if case != "unknown":
        for name, value in {
            "server_url": "ws://example.invalid/ocpp",
            "charge_point_id": "THOR-TEST",
            "power": 7210,
            "energy": 12345,
            "total_energy_charged": 512.34567,
            "electricity_price": 0.23456,
            "last_session_energy": 12.34567,
            "last_session_cost": 2.345,
            "last_session_duration_minutes": 123.5,
            "last_session_effective_charging_minutes": 119.5,
            "temperature": 27.5,
            "last_session_start": "2026-10-27T12:00:00+02:00",
            "last_session_end": "2026-10-27T13:00:00+02:00",
            "last_session_plug_time": "2026-10-27T11:59:00+02:00",
            "last_session_unplug_time": "2026-10-27T13:01:00+02:00",
            "last_session_transaction_id": "51",
            "last_session_charge_mode": "3",
            "last_session_work_mode": "PVlink",
            "grid_power": -1200,
            "currents": {"L1": 16, "L2": 15.5},
            "voltages": {"L1": 230, "L2": 231},
            "phase_power": {"L1": 3680, "L2": 3580},
            "grid_currents": {"L1": -2, "L2": 1},
            "grid_voltages": {"L1": 229, "L2": 232},
        }.items():
            setattr(c, name, value)
    return c


def projection(entity):
    description = getattr(entity, "entity_description", None)

    def metadata(name, fallback=None):
        return getattr(entity, "_attr_" + name, getattr(description, name, fallback))

    return {
        "unique_id": entity._attr_unique_id,
        "device": {
            **entity._attr_device_info,
            "identifiers": sorted(map(list, entity._attr_device_info["identifiers"])),
        },
        "state": entity.native_value,
        "available": entity.available,
        "attributes": getattr(entity, "extra_state_attributes", None),
        **{
            name: metadata(name)
            for name in (
                "translation_key",
                "translation_placeholders",
                "device_class",
                "state_class",
                "native_unit_of_measurement",
                "entity_category",
                "icon",
                "options",
                "suggested_display_precision",
            )
        },
        "unrecorded_attributes": sorted(getattr(entity, "_unrecorded_attributes", ())),
        "resolved_unit": getattr(
            entity, "native_unit_of_measurement", metadata("native_unit_of_measurement")
        ),
        "enabled_default": metadata("entity_registry_enabled_default", True),
    }


def snapshot(platform=sensor):
    result = {}
    for case in ("unknown", "reported", "disconnected", "coordinator_failed"):
        c = coordinator(case)
        result[case] = {
            name: projection(getattr(platform, name)(c, SimpleNamespace(entry_id="entry-test")))
            for name in SIMPLE
        }
        for name in PHASED:
            for phase in ("L1", "L2", "L3"):
                result[case][name + ":" + phase] = projection(
                    getattr(platform, name)(c, SimpleNamespace(entry_id="entry-test"), phase)
                )
    return result


class SensorDescriptionContractTest(unittest.TestCase):
    def test_sensor_contracts_preserve_existing_metadata_and_state(self):
        actual = snapshot()
        self.assertIs(
            type(
                actual["reported"]["LastSessionEffectiveChargingDurationSensor"]["attributes"][
                    "active_power_threshold_w"
                ]
            ),
            int,
        )
        self.assertEqual(actual, json.loads(CONTRACT.read_text()))
