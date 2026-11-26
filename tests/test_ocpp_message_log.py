"""The diagnostics ring buffer keeps OCPP frame metadata and redacted payloads."""

import json
import unittest
from unittest.mock import patch

from tests import test_authorization_ocpp as wire
from tests.support import load_package_module

message_log = load_package_module("ocpp.growatt.message_log")
AT = "2026-11-04T10:00:00Z"


def frame(*message):
    return json.dumps(list(message))


class OcppMessageLogTest(unittest.TestCase):
    def setUp(self):
        self.log = message_log.OcppMessageLog()

    def messages(self):
        return self.log.diagnostics()["messages"]

    def test_keeps_the_latest_frames_oldest_first(self):
        for index in range(60):
            self.log.record("in", frame(2, f"id-{index}", "Heartbeat", {}), AT)

        diagnostics = self.log.diagnostics()
        self.assertEqual(diagnostics["capacity"], 50)
        self.assertEqual(
            [message["unique_id"] for message in diagnostics["messages"]],
            [f"id-{index}" for index in range(10, 60)],
        )

    def test_records_metadata_and_correlates_answers_with_their_call(self):
        call = frame(2, "out-1", "GetConfiguration", {"key": ["G_MaxCurrent"]})
        self.log.record("out", call, AT)
        self.log.record("in", frame(3, "out-1", {"configurationKey": []}), AT)
        self.log.record("in", frame(2, "in-1", "Heartbeat", {}), AT)
        self.log.record("out", frame(4, "in-1", "InternalError", "boom", {"trace": "x"}), AT)

        first, result, heartbeat, error = self.messages()
        self.assertEqual(
            first,
            {
                "at": AT,
                "direction": "out",
                "message_type": "Call",
                "action": "GetConfiguration",
                "unique_id": "out-1",
                "size": len(call.encode()),
                "payload": {"key": ["G_MaxCurrent"]},
            },
        )
        self.assertEqual(
            (result["message_type"], result["action"], result["direction"]),
            ("CallResult", "GetConfiguration", "in"),
        )
        self.assertEqual(heartbeat["action"], "Heartbeat")
        self.assertEqual(
            (error["message_type"], error["action"], error["payload"]),
            (
                "CallError",
                "Heartbeat",
                {
                    "errorCode": "InternalError",
                    "errorDescription": "<redacted>",
                    "errorDetails": "<redacted>",
                },
            ),
        )

    def test_an_answer_only_matches_a_call_from_the_other_side(self):
        # Both sides choose unique ids independently, so the same id may appear
        # for an inbound and an outbound CALL at once.
        self.log.record("in", frame(2, "same", "Heartbeat", {}), AT)
        self.log.record("out", frame(2, "same", "TriggerMessage", {}), AT)
        self.log.record("in", frame(3, "same", {"status": "Accepted"}), AT)
        self.log.record("out", frame(3, "same", {"currentTime": AT}), AT)

        self.assertEqual(
            [message["action"] for message in self.messages()[2:]],
            ["TriggerMessage", "Heartbeat"],
        )

    def test_unanswered_calls_do_not_grow_without_bound(self):
        for index in range(200):
            self.log.record("out", frame(2, f"id-{index}", "TriggerMessage", {}), AT)

        self.assertLessEqual(len(self.log._pending_calls), 50)

    def test_invalid_frames_keep_only_metadata(self):
        self.log.record("in", "not json idTag=PRIVATE", AT)
        self.log.record("in", frame(9, "x", "Heartbeat"), AT)
        # A redaction failure must not escape into the OCPP router.
        with patch.object(message_log, "_redact_call_result", side_effect=ValueError):
            self.log.record("in", frame(3, "y", {"idTag": "PRIVATE"}), AT)

        for message in self.messages():
            self.assertEqual(
                (message["message_type"], message["action"], message["payload"]),
                ("Invalid", None, None),
            )

    def test_identifiers_configuration_values_and_session_data_are_redacted(self):
        records = [
            ("in", frame(2, "a", "Authorize", {"idTag": "PRIVATE-RFID"})),
            ("out", frame(3, "a", {"idTagInfo": {"status": "Accepted", "parentIdTag": "P"}})),
            (
                "out",
                frame(2, "b", "ChangeConfiguration", {"key": "G_ServerURL", "value": "ws://h"}),
            ),
            ("out", frame(2, "c", "ChangeConfiguration", {"key": "G_MaxCurrent", "value": "16"})),
            ("out", frame(2, "d", "GetConfiguration", {})),
            (
                "in",
                frame(
                    3,
                    "d",
                    {
                        "configurationKey": [
                            {"key": "G_MaxCurrent", "value": "16", "readonly": False},
                            {"key": "G_ChargerNetIP", "value": "192.0.2.42"},
                            {"key": "FutureKey", "value": "secret"},
                        ],
                        "unknownKey": ["Missing"],
                    },
                ),
            ),
            (
                "in",
                frame(
                    2,
                    "e",
                    "DataTransfer",
                    {"vendorId": "Growatt", "messageId": "currentrecord", "data": "card=PRIVATE"},
                ),
            ),
            ("out", frame(2, "f", "DataTransfer", {"messageId": "get_external_meterval"})),
            ("in", frame(3, "f", {"status": "Accepted", "data": "meterval=1"})),
            ("in", frame(3, "unknown", {"data": "card=PRIVATE"})),
            ("in", frame(3, "unknown", {"configurationKey": [{"key": "X", "value": "secret"}]})),
        ]
        for direction, raw in records:
            self.log.record(direction, raw, AT)

        payloads = [message["payload"] for message in self.messages()]
        self.assertEqual(payloads[0], {"idTag": "<redacted>"})
        self.assertEqual(
            payloads[1], {"idTagInfo": {"status": "Accepted", "parentIdTag": "<redacted>"}}
        )
        self.assertEqual(payloads[2], {"key": "G_ServerURL", "value": "<redacted>"})
        self.assertEqual(payloads[3], {"key": "G_MaxCurrent", "value": "16"})
        self.assertEqual(
            payloads[5],
            {
                "configurationKey": [
                    {"key": "G_MaxCurrent", "value": "16", "readonly": False},
                    {"key": "G_ChargerNetIP", "value": "<redacted>"},
                    {"key": "FutureKey", "value": "<redacted>"},
                ],
                "unknownKey": ["Missing"],
            },
        )
        self.assertEqual(payloads[6]["data"], "<redacted>")
        self.assertEqual(payloads[8], {"status": "Accepted", "data": "meterval=1"})
        # Answers whose CALL already left the log get every redaction rule.
        self.assertEqual(payloads[9], {"data": "<redacted>"})
        self.assertEqual(payloads[10], {"configurationKey": [{"key": "X", "value": "<redacted>"}]})
        serialized = json.dumps(self.log.diagnostics())
        for secret in ("PRIVATE", "ws://h", "192.0.2.42", '"secret"'):
            self.assertNotIn(secret, serialized)


@unittest.skipUnless(wire.HAS_OCPP, "Install tests/requirements-auth.txt for real OCPP tests")
class ChargePointMessageLogTest(wire.AuthorizationWireTest):
    """Reuse the wire harness: a real GrowattChargePoint on a fake socket."""

    def messages(self):
        return self.coordinator.ocpp_messages.diagnostics()["messages"]

    async def test_records_inbound_calls_and_their_replies(self):
        await self.start("PRIVATE-CARD")

        call, reply = self.messages()
        self.assertEqual(
            (call["direction"], call["message_type"], call["action"], call["unique_id"]),
            ("in", "Call", "StartTransaction", "test-message"),
        )
        self.assertEqual(
            (reply["direction"], reply["message_type"], reply["action"]),
            ("out", "CallResult", "StartTransaction"),
        )
        self.assertEqual(call["at"], self.coordinator.now())
        self.assertNotIn("PRIVATE-CARD", json.dumps(self.messages()))

    async def test_superseded_connection_records_nothing(self):
        replacement = wire.server.GrowattChargePoint(
            "TEST-CHARGER", wire.Websocket(), self.coordinator, self.hass
        )
        self.assertIsNot(self.coordinator.runtime_data["charge_point"], self.cp)

        await self.cp.route_message(frame(2, "stale", "Heartbeat", {}))
        await self.cp._send(frame(3, "stale", {}))

        self.assertEqual(self.messages(), [])
        await replacement.route_message(frame(2, "fresh", "Heartbeat", {}))
        self.assertEqual([message["unique_id"] for message in self.messages()], ["fresh", "fresh"])


# The inherited authorization tests already run in their own module.
for _name in [name for name in vars(wire.AuthorizationWireTest) if name.startswith("test_")]:
    setattr(ChargePointMessageLogTest, _name, None)


if __name__ == "__main__":
    unittest.main()
