"""Typed HA core decorators; every other core name stays untyped (Any)."""

from collections.abc import Callable
from typing import Any

def callback[F: Callable[..., Any]](func: F) -> F: ...
def __getattr__(name: str) -> Any: ...
