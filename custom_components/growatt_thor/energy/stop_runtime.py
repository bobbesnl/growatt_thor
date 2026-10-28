"""Compatibility imports for energy.stop_guard."""

from importlib import import_module as _import_module

from .stop_guard import *  # noqa: F403 - compatibility re-exports

_module = _import_module(".stop_guard", __package__)


def __getattr__(name):
    return getattr(_module, name)
