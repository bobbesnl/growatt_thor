"""Compile-only checks: concrete owners must implement their advertised capabilities."""

from custom_components.growatt_thor.configuration.contracts import ConfigurationWriteOwner
from custom_components.growatt_thor.coordinator import GrowattCoordinator
from custom_components.growatt_thor.energy.contracts import EnergyStopOwner
from custom_components.growatt_thor.presentation.contracts import DashboardOwner
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
