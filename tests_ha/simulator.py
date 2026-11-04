"""A minimal OCPP 1.6 charge point that talks to the integration over a real socket.

It answers the requests the integration sends after connecting and records the
remote commands it receives. The behavior is configurable per test, so a test
can accept, reject or ignore a command. It does not model THOR firmware beyond
the messages the scenarios need.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import websockets
from ocpp.routing import on
from ocpp.v16 import ChargePoint, call, call_result
from ocpp.v16.enums import (
    Action,
    ConfigurationStatus,
    DataTransferStatus,
    RemoteStartStopStatus,
    TriggerMessageStatus,
)


def now() -> str:
    return datetime.now(UTC).isoformat()


class SimulatedThor(ChargePoint):
    """Charge point side of the OCPP connection."""

    def __init__(self, charge_point_id: str, connection: Any) -> None:
        super().__init__(charge_point_id, connection, response_timeout=5)
        self.remote_start_status = RemoteStartStopStatus.accepted
        self.remote_stop_status = RemoteStartStopStatus.accepted
        self.remote_starts: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.remote_stops: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        # When set, RemoteStop is answered only after the event fires. The
        # library handles one frame at a time, so the simulator stays silent
        # until then, like a THOR that lost the answer.
        self.hold_remote_stop_answer: asyncio.Event | None = None

    # Requests from the integration

    @on(Action.get_configuration)
    def on_get_configuration(self, key: list[str] | None = None) -> call_result.GetConfiguration:
        return call_result.GetConfiguration(configuration_key=[], unknown_key=key or [])

    @on(Action.trigger_message)
    def on_trigger_message(self, **_: Any) -> call_result.TriggerMessage:
        return call_result.TriggerMessage(status=TriggerMessageStatus.accepted)

    @on(Action.data_transfer)
    def on_data_transfer(self, **_: Any) -> call_result.DataTransfer:
        return call_result.DataTransfer(status=DataTransferStatus.rejected)

    @on(Action.change_configuration)
    def on_change_configuration(self, **_: Any) -> call_result.ChangeConfiguration:
        return call_result.ChangeConfiguration(status=ConfigurationStatus.accepted)

    @on(Action.remote_start_transaction)
    def on_remote_start(self, id_tag: str, **kwargs: Any) -> call_result.RemoteStartTransaction:
        self.remote_starts.put_nowait({"id_tag": id_tag, **kwargs})
        return call_result.RemoteStartTransaction(status=self.remote_start_status)

    @on(Action.remote_stop_transaction)
    async def on_remote_stop(self, transaction_id: int) -> call_result.RemoteStopTransaction:
        self.remote_stops.put_nowait({"transaction_id": transaction_id})
        if self.hold_remote_stop_answer is not None:
            await self.hold_remote_stop_answer.wait()
        return call_result.RemoteStopTransaction(status=self.remote_stop_status)

    # Messages the charger sends

    async def boot(self) -> Any:
        return await self.call(
            call.BootNotification(
                charge_point_vendor="Growatt",
                charge_point_model="THOR 11AS",
                firmware_version="THOR_11AS-SIM",
            )
        )

    async def status(self, status: str, error_code: str = "NoError") -> Any:
        return await self.call(
            call.StatusNotification(
                connector_id=1, error_code=error_code, status=status, timestamp=now()
            )
        )

    async def start_transaction(self, id_tag: str, meter_start: int) -> Any:
        return await self.call(
            call.StartTransaction(
                connector_id=1, id_tag=id_tag, meter_start=meter_start, timestamp=now()
            )
        )

    async def meter_values(self, transaction_id: int, power_w: float, energy_wh: float) -> Any:
        return await self.call(
            call.MeterValues(
                connector_id=1,
                transaction_id=transaction_id,
                meter_value=[
                    {
                        "timestamp": now(),
                        "sampled_value": [
                            {
                                "value": str(power_w),
                                "measurand": "Power.Active.Import",
                                "unit": "W",
                            },
                            {
                                "value": str(energy_wh),
                                "measurand": "Energy.Active.Import.Register",
                                "unit": "Wh",
                            },
                        ],
                    }
                ],
            )
        )

    async def stop_transaction(self, transaction_id: int, meter_stop: int, reason: str) -> Any:
        return await self.call(
            call.StopTransaction(
                transaction_id=transaction_id,
                meter_stop=meter_stop,
                timestamp=now(),
                reason=reason,
            )
        )


@asynccontextmanager
async def connected_thor(
    port: int, charge_point_id: str = "THOR-SIM"
) -> AsyncIterator[SimulatedThor]:
    """Connect a simulated charger and close the socket when the test is done."""
    connection = await websockets.connect(
        f"ws://127.0.0.1:{port}/ocpp/ws/{charge_point_id}",
        subprotocols=["ocpp1.6"],
        ping_interval=None,
    )
    thor = SimulatedThor(charge_point_id, connection)
    listener = asyncio.create_task(thor.start())
    try:
        yield thor
    finally:
        await connection.close()
        listener.cancel()
        try:
            await listener
        except (asyncio.CancelledError, websockets.exceptions.ConnectionClosed):
            pass
