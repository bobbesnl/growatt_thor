"""Compatibility imports for energy.site_observations."""

from importlib import import_module as _import_module

from .site_observations import *  # noqa: F403 - compatibility re-exports

_module = _import_module(".site_observations", __package__)


def __getattr__(name):
    return getattr(_module, name)
