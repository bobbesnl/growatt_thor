"""Compatibility imports for energy.allocation."""

from importlib import import_module as _import_module

from .allocation import *  # noqa: F403 - compatibility re-exports

_module = _import_module(".allocation", __package__)


def __getattr__(name):
    return getattr(_module, name)
