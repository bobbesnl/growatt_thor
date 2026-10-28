"""Compatibility imports for sessions.display_times."""

from importlib import import_module as _import_module

from .display_times import *  # noqa: F403 - compatibility re-exports

_module = _import_module(".display_times", __package__)


def __getattr__(name):
    return getattr(_module, name)
