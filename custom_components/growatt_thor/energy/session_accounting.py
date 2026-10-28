"""Compatibility imports for energy.session_accumulator."""

from importlib import import_module as _import_module

from .session_accumulator import *  # noqa: F403 - compatibility re-exports

_module = _import_module(".session_accumulator", __package__)


def __getattr__(name):
    return getattr(_module, name)
