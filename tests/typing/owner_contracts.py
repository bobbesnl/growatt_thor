"""Compile-only checks: concrete owners must implement their advertised capabilities."""

from custom_components.growatt_thor.charging.contracts import PvServiceOwner
from custom_components.growatt_thor.configuration.contracts import ConfigurationWriteOwner
from custom_components.growatt_thor.coordinator import GrowattCoordinator
from custom_components.growatt_thor.energy.contracts import EnergyStopOwner
from custom_components.growatt_thor.presentation.contracts import DashboardOwner
from custom_components.growatt_thor.runtime.charger_write_queue import WriteQueueOwner
from custom_components.growatt_thor.sessions.contracts import DashboardHistoryOwner, SessionOwner


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
