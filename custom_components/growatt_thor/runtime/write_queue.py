"""Compatibility imports for runtime.write_results."""

from importlib import import_module as _import_module

from .write_results import *  # noqa: F403 - compatibility re-exports

_module = _import_module(".write_results", __package__)


def __getattr__(name):
    return getattr(_module, name)
