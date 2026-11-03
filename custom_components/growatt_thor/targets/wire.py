"""Narrow adapter for the extra connectorId captured in Growatt DataTransfer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ocpp.v16 import call

from ..coerce import enum_value
from .model import ChargingTarget


class OcppCaller(Protocol):
    async def call(self, payload: object, **kwargs: Any) -> Any: ...


@dataclass
class DataTransfer(call.DataTransfer):
    # The OCPP library derives the action from the class name. Keep DataTransfer.
    connector_id: int = 1


async def send_target(charge_point: OcppCaller, target: ChargingTarget) -> str:
    payload = target.payload()
    result = await charge_point.call(
        DataTransfer(
            vendor_id=payload["vendorId"],
            message_id=payload["messageId"],
            data=payload["data"],
            connector_id=1,
        ),
        suppress=False,
        # Only this locally validated extension bypasses the standard schema;
        # every other OCPP call retains its existing schema checks.
        skip_schema_validation=True,
    )
    status = getattr(result, "status", None)
    status = enum_value(status)
    if status not in {"Accepted", "Rejected", "UnknownMessageId", "UnknownVendorId"}:
        raise ValueError("invalid_target_response")
    return str(status)
