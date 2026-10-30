"""Guarded charger operations used inside the target runtime's queue callbacks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ocpp.v16 import call as ocpp_call

from ..charging.control_capabilities import selected_working_mode
from ..configuration.values import configuration_entity_state
from ..ocpp.diagnostics import boot_notification_field
from ..runtime.keys import ACTIVE_CHARGE_POINT
from .model import CAPTURE_FIRMWARE
from .requests import TargetRecord

if TYPE_CHECKING:
    from ..coordinator import GrowattCoordinator
    from ..ocpp.server import GrowattChargePoint


def _response_status(result: object) -> str | None:
    status = getattr(result, "status", None)
    status = getattr(status, "value", status)
    return status if isinstance(status, str) else None


@dataclass(slots=True)
class TargetChargerOperations:
    coordinator: GrowattCoordinator

    def charger_mode(self) -> str | None:
        return configuration_entity_state(
            "G_ChargerMode", self.coordinator.configuration_values.get("G_ChargerMode")
        )

    def remote_identifier_reason(self, cp: GrowattChargePoint) -> str | None:
        if not isinstance(cp.id, str) or not 1 <= len(cp.id) <= 20:
            return "remote_identifier_invalid"
        if (
            self.charger_mode() == "home_assistant_rfid"
            and not self.coordinator.authorization.policy.allows_ha_remote_start()
        ):
            return "remote_identifier_not_authorized"
        return None

    def block_reason(self, cp: GrowattChargePoint | None, activation: str) -> str | None:
        if (
            not self.coordinator.connected
            or cp is None
            or self.coordinator.runtime_data.get(ACTIVE_CHARGE_POINT) is not cp
        ):
            return "charger_disconnected_or_replaced"
        if self.coordinator.transaction_is_active:
            return "transaction_already_active"
        if self.coordinator.charger_is_faulted:
            return "charger_not_ready"
        if (
            boot_notification_field(self.coordinator.boot_notification, "firmware_version")
            != CAPTURE_FIRMWARE
        ):
            return "firmware_not_validated_for_pilot"
        if selected_working_mode(self.coordinator.configuration_values) != "fast":
            return "fast_mode_required"

        mode = self.charger_mode()
        status = self.coordinator.status
        if activation == "plug":
            if mode != "plug_and_charge":
                return "plug_and_charge_mode_required"
            return None if status == "Available" else "unplug_vehicle_before_setting_target"
        if activation == "rfid":
            if mode != "rfid_only":
                return "rfid_authorization_mode_required"
            return None if status in {"Available", "Preparing"} else "charger_not_ready"
        if activation == "reserve":
            if mode not in {"plug_and_charge", "home_assistant_rfid"}:
                return "remote_start_authorization_mode_required"
            # The target write precedes ReserveNow. Requiring an unplugged,
            # Available connector prevents Plug & Charge from starting early.
            if status != "Available":
                return "unplug_vehicle_before_setting_reservation"
            return self.remote_identifier_reason(cp)
        if activation == "reserved_start":
            if mode not in {"plug_and_charge", "home_assistant_rfid"}:
                return "remote_start_authorization_mode_required"
            # Growatt expires the captured reservation at the selected start
            # boundary. Depending on notification timing the connector can
            # already be Available or Preparing when this callback runs.
            if status not in {"Reserved", "Available", "Preparing"}:
                return "charger_reservation_not_active"
            return self.remote_identifier_reason(cp)
        if activation == "daily_start":
            if mode not in {"plug_and_charge", "home_assistant_rfid"}:
                return "remote_start_authorization_mode_required"
            if mode == "plug_and_charge" and status != "Preparing":
                return "vehicle_must_be_connected_at_daily_start"
            if status not in {"Available", "Preparing"}:
                return "charger_not_ready"
            return self.remote_identifier_reason(cp)
        if mode not in {"plug_and_charge", "home_assistant_rfid"}:
            return "remote_start_authorization_mode_required"
        if status not in {"Available", "Preparing"}:
            return "charger_not_ready"
        return self.remote_identifier_reason(cp)

    async def remote_start(self, cp: GrowattChargePoint) -> str:
        authorization = self.coordinator.authorization
        if not authorization.begin_ha_remote_start(cp.id):
            return "Rejected"
        try:
            result = await cp.call(
                ocpp_call.RemoteStartTransaction(connector_id=1, id_tag=cp.id),
                suppress=False,
            )
        except Exception:
            authorization.cancel_ha_remote_start()
            raise
        status = _response_status(result)
        if status not in {"Accepted", "Rejected"}:
            authorization.cancel_ha_remote_start()
            raise ValueError("invalid_start_response")
        if status != "Accepted":
            authorization.cancel_ha_remote_start()
        return status

    async def reserve(self, cp: GrowattChargePoint, request: TargetRecord) -> str:
        result = await cp.call(
            ocpp_call.ReserveNow(
                connector_id=1,
                expiry_date=request["reservation_expiry"],
                id_tag=cp.id,
                reservation_id=request["reservation_id"],
            ),
            suppress=False,
        )
        status = _response_status(result)
        valid = {"Accepted", "Faulted", "Occupied", "Rejected", "Unavailable"}
        if status not in valid:
            raise ValueError("invalid_reservation_response")
        return status

    async def cancel_reservation(self, cp: GrowattChargePoint, reservation_id: int) -> str:
        result = await cp.call(
            ocpp_call.CancelReservation(reservation_id=reservation_id), suppress=False
        )
        status = _response_status(result)
        if status not in {"Accepted", "Rejected"}:
            raise ValueError("invalid_cancel_response")
        return status
