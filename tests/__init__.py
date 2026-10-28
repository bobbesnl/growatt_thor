"""Regression suites use shared HA stand-ins without starting Home Assistant."""

from .support import install_coordinator_stubs

install_coordinator_stubs()
