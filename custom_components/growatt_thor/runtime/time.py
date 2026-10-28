"""Compatibility imports for timestamps."""

from importlib import import_module as _import_module

from ..timestamps import *  # noqa: F403 - compatibility re-exports

_module = _import_module("..timestamps", __package__)


def __getattr__(name):
    return getattr(_module, name)
