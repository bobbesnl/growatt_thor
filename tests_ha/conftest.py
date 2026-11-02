"""Fixtures for tests against a real Home Assistant core.

These tests run in their own environment (see tests_ha/requirements-*.txt):
the unit suites in tests/ replace ``homeassistant`` with stand-ins, so both
cannot share one Python process.
"""

from __future__ import annotations

import socket
from collections.abc import Generator

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growatt_thor.const import (
    CONF_BIND_ADDRESS,
    CONF_LOCATION,
    CONF_POLL_INTERVAL,
    CONF_PORT,
    CONFIG_ENTRY_VERSION,
    DOMAIN,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the integration from custom_components/ in every test."""


@pytest.fixture(autouse=True)
def allow_local_sockets(socket_enabled: None) -> None:
    """The integration runs a real OCPP server; tests bind it to localhost."""


def free_port() -> int:
    """Return a TCP port on 127.0.0.1 that is free right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True


@pytest.fixture
def ocpp_port() -> int:
    return free_port()


@pytest.fixture
def config_entry(ocpp_port: int) -> Generator[MockConfigEntry]:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Growatt THOR EV Charger",
        version=CONFIG_ENTRY_VERSION,
        data={
            CONF_PORT: ocpp_port,
            CONF_BIND_ADDRESS: "127.0.0.1",
            CONF_LOCATION: "",
            CONF_POLL_INTERVAL: 30,
        },
    )
    yield entry
