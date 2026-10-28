"""Compatibility imports for charging.start_stop_rules."""

from importlib import import_module as _import_module

from .start_stop_rules import *  # noqa: F403 - compatibility re-exports

_module = _import_module(".start_stop_rules", __package__)


def __getattr__(name):
    return getattr(_module, name)
