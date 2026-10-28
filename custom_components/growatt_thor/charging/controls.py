"""Compatibility imports for charging.control_capabilities."""

from importlib import import_module as _import_module

from .control_capabilities import *  # noqa: F403 - compatibility re-exports

_module = _import_module(".control_capabilities", __package__)


def __getattr__(name):
    return getattr(_module, name)
