"""Config-entry identity and typed runtime used at HA setup boundaries."""

from collections.abc import Mapping
from typing import Any, Generic

from typing_extensions import TypeVar

T = TypeVar("T", default=Any)

class ConfigEntry(Generic[T]):
    entry_id: str
    title: str
    data: Mapping[str, Any]
    options: Mapping[str, Any]
    runtime_data: T
