"""Compile-only checks: concrete owners must implement their advertised capabilities."""

from custom_components.growatt_thor.charging.contracts import (
    PvApplyTransport,
    PvServiceOwner,
    TransactionTransport,
)
from custom_components.growatt_thor.charging.control import ChargerControl, NativeTargetControl
from custom_components.growatt_thor.charging.growatt_charger import GrowattOcppCharger
from custom_components.growatt_thor.configuration.contracts import (
    ConfigurationTransport,
    ConfigurationWriteOwner,
)
from custom_components.growatt_thor.coordinator import GrowattCoordinator
from custom_components.growatt_thor.energy.contracts import EnergyStopOwner
from custom_components.growatt_thor.ocpp.growatt.server import GrowattChargePoint
from custom_components.growatt_thor.presentation.contracts import DashboardOwner
from custom_components.growatt_thor.runtime.charger_write_queue import WriteQueueOwner
from custom_components.growatt_thor.runtime.services import RefreshTransport
from custom_components.growatt_thor.sessions.contracts import DashboardHistoryOwner, SessionOwner
from custom_components.growatt_thor.targets.charger_ops import TargetChargerOperations
from tests.support.charger_control import FakeChargerControl


def dashboard_owner(coordinator: GrowattCoordinator) -> DashboardOwner:
    return coordinator


def configuration_owner(coordinator: GrowattCoordinator) -> ConfigurationWriteOwner:
    return coordinator


def energy_stop_owner(coordinator: GrowattCoordinator) -> EnergyStopOwner:
    return coordinator


def session_owner(coordinator: GrowattCoordinator) -> SessionOwner:
    return coordinator


def history_owner(coordinator: GrowattCoordinator) -> DashboardHistoryOwner:
    return coordinator


def pv_service_owner(coordinator: GrowattCoordinator) -> PvServiceOwner:
    return coordinator


def write_queue_owner(coordinator: GrowattCoordinator) -> WriteQueueOwner:
    return coordinator


def transaction_transport(charger: GrowattChargePoint) -> TransactionTransport:
    return charger


def configuration_transport(charger: GrowattChargePoint) -> ConfigurationTransport:
    return charger


def pv_transport(charger: GrowattChargePoint) -> PvApplyTransport:
    return charger


def refresh_transport(charger: GrowattChargePoint) -> RefreshTransport:
    return charger


def charger_control(charger: GrowattOcppCharger) -> ChargerControl:
    return charger


def fake_charger_control(charger: FakeChargerControl) -> ChargerControl:
    return charger


def native_target_control(operations: TargetChargerOperations) -> NativeTargetControl:
    return operations
