"""Two chargers on the real OCPP handlers; install tests/requirements-auth.txt.

Backlog F09: connections and session state are scoped to each charger, and a
reconnect or connection for one charger cannot affect another.
"""
import asyncio
import importlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest

HAS_OCPP = (
    importlib.util.find_spec("ocpp") is not None
    and importlib.util.find_spec("websockets") is not None
)
if HAS_OCPP:
    # Load the actual integration modules without executing HA's package setup.
    package = ModuleType("thor_multi_charger_target")
    package.__path__ = [
        str(Path(__file__).parents[1] / "custom_components/growatt_thor")
    ]
    sys.modules[package.__name__] = package
    server = importlib.import_module(package.__name__ + ".ocpp.server")
    auth = importlib.import_module(package.__name__ + ".charging.authorization")


class Websocket:
    def __init__(self):
        self.sent = []
        self.closed = []

    async def send(self, value):
        self.sent.append(json.loads(value))

    async def close(self, code=None, reason=None):
        self.closed.append((code, reason))


class Coordinator:
    """Minimal coordinator with its own per-entry runtime mapping."""

    def __init__(self):
        self.runtime_data = {}
        self.authorization = auth.LocalAuthorization()
        self.charger_mode = 1
        self.connected = True
        self.has_pending_charger_writes = False
        self.charge_point_id = None
        self.statuses = []

    def now(self):
        return "2026-10-20T10:00:00Z"

    def set_charge_point(self, cp_id):
        self.charge_point_id = cp_id

    def mark_connection_activity(self, action):
        pass

    def record_status_notification(self, connector_id, status, error_code=None, **kwargs):
        self.statuses.append(status)


@unittest.skipUnless(HAS_OCPP, "Install tests/requirements-auth.txt for OCPP handler tests")
class TwoChargerConnectionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = SimpleNamespace(data={}, loop=asyncio.get_running_loop())
        self.left = Coordinator()
        self.right = Coordinator()
        self.left_cp = server.GrowattChargePoint(
            "THOR-LEFT", Websocket(), self.left, self.hass
        )
        self.right_cp = server.GrowattChargePoint(
            "THOR-RIGHT", Websocket(), self.right, self.hass
        )

    async def status(self, charge_point, status):
        await charge_point.route_message(json.dumps([
            2,
            "status-1",
            "StatusNotification",
            {"connectorId": 1, "errorCode": "NoError", "status": status},
        ]))

    async def test_each_charger_owns_its_own_connection_slot(self):
        self.assertIs(self.left.runtime_data["charge_point"], self.left_cp)
        self.assertIs(self.right.runtime_data["charge_point"], self.right_cp)
        self.assertEqual(self.hass.data, {})

    async def test_messages_only_update_their_own_coordinator(self):
        await self.status(self.left_cp, "Charging")
        await self.status(self.right_cp, "Available")

        self.assertEqual(self.left.statuses, ["Charging"])
        self.assertEqual(self.right.statuses, ["Available"])

    async def test_reconnect_of_one_charger_leaves_the_other_untouched(self):
        replacement = server.GrowattChargePoint(
            "THOR-LEFT", Websocket(), self.left, self.hass
        )

        self.assertIs(self.left.runtime_data["charge_point"], replacement)
        self.assertIs(self.right.runtime_data["charge_point"], self.right_cp)

        # The superseded left socket is ignored; the right charger still works.
        await self.status(self.left_cp, "Faulted")
        await self.status(self.right_cp, "Charging")
        self.assertEqual(self.left.statuses, [])
        self.assertEqual(self.right.statuses, ["Charging"])

    async def test_other_charger_on_one_entry_is_rejected_without_affecting_either(self):
        intruder = Websocket()

        with self.assertLogs(server._LOGGER, level="ERROR"):
            await server._on_connect(
                intruder,
                "/ocpp/ws/THOR-RIGHT",
                self.left,
                self.hass,
            )

        self.assertEqual(intruder.closed[0][0], 1008)
        self.assertIs(self.left.runtime_data["charge_point"], self.left_cp)
        self.assertIs(self.right.runtime_data["charge_point"], self.right_cp)
        self.assertEqual(self.left.charge_point_id, "THOR-LEFT")
        self.assertEqual(self.right.charge_point_id, "THOR-RIGHT")

    async def test_release_of_one_connection_keeps_the_other(self):
        self.assertTrue(
            server.release_active_charge_point(
                self.left.runtime_data,
                self.left_cp,
            )
        )
        self.assertNotIn("charge_point", self.left.runtime_data)
        self.assertIs(self.right.runtime_data["charge_point"], self.right_cp)


if __name__ == "__main__":
    unittest.main()
