"""Capture-derived target encoding and failure-path regression tests."""

import asyncio
import importlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock

package = ModuleType("thor_goal_test_target")
package.__path__ = [str(Path(__file__).parents[1] / "custom_components/growatt_thor")]
sys.modules[package.__name__] = package
model = importlib.import_module(package.__name__ + ".targets.model")
runner = importlib.import_module(package.__name__ + ".targets.runner")


class TargetEncodingTest(unittest.TestCase):
    def test_capture_payloads_include_vendor_connector_extension(self):
        for kind, value, message, encoded in [
            ("duration", "60", "G_SetTime", "60"),
            ("energy", "4", "G_SetEnergy", "4"),
            ("budget", "49,99", "G_SetAmount", "49,99"),
        ]:
            self.assertEqual(
                model.ChargingTarget.parse(kind, value).payload(),
                {
                    "vendorId": "Growatt",
                    "messageId": message,
                    "connectorId": 1,
                    "data": encoded,
                },
            )

    def test_values_are_finite_bounded_and_unambiguous(self):
        for value in [
            True,
            False,
            "nan",
            "inf",
            "1e2",
            "0",
            "-1",
            "1,000.50",
            "0.001",
            "100.01",
        ]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                model.ChargingTarget.parse("energy", value)
        for value in ["0.5", "1441"]:
            with self.assertRaises(ValueError):
                model.ChargingTarget.parse("duration", value)
        self.assertEqual(
            model.ChargingTarget.parse("duration", "60.00").wire_value, "60"
        )
        self.assertEqual(model.ChargingTarget.parse("energy", "4.50").wire_value, "4.5")

    def test_capture_matrix_reports_supported_activation_and_stop_evidence(self):
        for kind in model.MESSAGE_IDS:
            for start in ["now", "once", "recurring"]:
                plan = model.target_plan(model.ChargingTarget.parse(kind, "4"), start)
                self.assertTrue(plan["pilot_supported"])
                self.assertNotIn("capture", plan)
                self.assertEqual(
                    plan["automatic_stop_verified"], kind in {"duration", "energy"}
                )
        plan = model.target_plan(model.ChargingTarget.parse("budget", "49.99"), "once")
        self.assertEqual(
            plan["activation"], "ReserveNow+target+RemoteStartTransaction"
        )
        self.assertNotIn("expiryDate", plan)  # no fabricated conversion to start time

    def test_budget_blocks_sub_unit_firmware_edge_case(self):
        for value in ["0.01", "0.10", "0.99"]:
            with self.assertRaises(ValueError):
                model.ChargingTarget.parse("budget", value)
        self.assertEqual(model.ChargingTarget.parse("budget", "1").wire_value, "1")


class TargetSequenceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.states = []
        self.target = model.ChargingTarget.parse("duration", "1")
        self.send = AsyncMock(return_value="Accepted")
        self.start = AsyncMock(return_value="Accepted")
        self.sleep = AsyncMock()

    async def run_sequence(self, check=lambda: None):
        async def save(state):
            self.states.append(state)

        await runner.run_target_sequence(
            self.target,
            check=check,
            save=save,
            send_target=self.send,
            start=self.start,
            pause_seconds=20,
            sleep=self.sleep,
        )

    async def test_accepted_is_not_physical_completion(self):
        await self.run_sequence()
        self.assertEqual(
            self.states,
            ["sending_target", "target_accepted", "sending_start", "start_accepted"],
        )
        self.sleep.assert_awaited_once_with(20)

    async def test_block_before_any_write(self):
        await self.run_sequence(lambda: "disconnected")
        self.send.assert_not_called()
        self.start.assert_not_called()
        self.assertEqual(self.states, ["blocked_before_target"])

    async def test_disconnect_or_new_transaction_between_writes_blocks_start(self):
        checks = iter([None, "changed"])
        await self.run_sequence(lambda: next(checks))
        self.start.assert_not_called()
        self.assertEqual(self.states[-1], "target_accepted_start_blocked")

    async def test_rejected_target_never_starts(self):
        self.send.return_value = "Rejected"
        await self.run_sequence()
        self.start.assert_not_called()
        self.assertEqual(self.states[-1], "target_rejected")

    async def test_timeout_is_unknown_and_not_retried(self):
        self.send.side_effect = TimeoutError("private payload")
        await self.run_sequence()
        self.send.assert_awaited_once()
        self.start.assert_not_called()
        self.assertEqual(self.states[-1], "outcome_unknown")

    async def test_start_rejection_retains_target_warning(self):
        self.start.return_value = "Rejected"
        await self.run_sequence()
        self.assertEqual(self.states[-1], "start_rejected_target_may_remain")

    async def test_cancellation_does_not_restart_or_clear_intent(self):
        self.sleep.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.run_sequence()
        self.start.assert_not_called()
        self.assertEqual(self.states[-1], "target_accepted")


class ReservationSequenceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.states = []
        self.target = model.ChargingTarget.parse("energy", "1")
        self.send = AsyncMock(return_value="Accepted")
        self.reserve = AsyncMock(return_value="Accepted")
        self.sleep = AsyncMock()

    async def run_sequence(self, check=lambda: None):
        async def save(state):
            self.states.append(state)

        await runner.run_reservation_sequence(
            self.target,
            check=check,
            save=save,
            send_target=self.send,
            reserve=self.reserve,
            sleep=self.sleep,
        )

    async def test_target_is_accepted_before_reservation(self):
        await self.run_sequence()
        self.assertEqual(
            self.states,
            ["sending_target", "target_accepted", "sending_reservation", "scheduled"],
        )
        self.reserve.assert_awaited_once()

    async def test_rejected_target_never_reserves(self):
        self.send.return_value = "Rejected"
        await self.run_sequence()
        self.reserve.assert_not_called()
        self.assertEqual(self.states[-1], "target_rejected")

    async def test_rejected_reservation_retains_target_warning(self):
        self.reserve.return_value = "Occupied"
        await self.run_sequence()
        self.assertEqual(self.states[-1], "reservation_rejected_target_may_remain")

    async def test_disconnect_between_target_and_reservation_blocks_it(self):
        checks = iter([None, "connection_changed"])
        await self.run_sequence(lambda: next(checks))
        self.reserve.assert_not_called()
        self.assertEqual(self.states[-1], "target_accepted_reservation_blocked")


@unittest.skipUnless(
    importlib.util.find_spec("ocpp"), "Requires tests/requirements-auth.txt"
)
class TargetWireTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_ocpp_serialization_preserves_connector_id(self):
        from ocpp.messages import CallResult
        from ocpp.v16 import ChargePoint

        wire = importlib.import_module(package.__name__ + ".targets.wire")
        cp = ChargePoint("TEST", None)
        cp._send = AsyncMock()
        cp._get_specific_response = AsyncMock(
            return_value=CallResult("test", {"status": "Accepted"})
        )
        for kind, value in [("duration", "60"), ("energy", "4"), ("budget", "49,99")]:
            target = model.ChargingTarget.parse(kind, value)
            self.assertEqual(await wire.send_target(cp, target), "Accepted")
            frame = json.loads(cp._send.call_args.args[0])
            self.assertEqual(frame[2], "DataTransfer")
            self.assertEqual(frame[3], target.payload())
