"""Typed per-entry resources with the existing ownership mapping contract."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator, MutableMapping
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from websockets.legacy.server import WebSocketServer

    from ..coordinator import GrowattCoordinator
    from ..energy.stop_guard import EnergyStopGuard
    from ..ocpp.server import GrowattChargePoint
    from ..targets.runtime import ChargingTargetRuntime
    from .polling import PollIntervalSchedule

    type ThorConfigEntry = ConfigEntry[EntryRuntime]


@dataclass(slots=True, eq=False)
class EntryRuntime(MutableMapping[str, Any]):
    """Own one entry's resources; keys remain stable for dispatch and queue users.

    HA platforms use typed attributes without looking up resources through
    ``hass.data``. Queue and dispatch users retain their mapping interface.
    Presence is tracked separately: a missing callback and an explicit ``None``
    retain their original mapping semantics during setup and teardown.
    """

    config_entry_id: str | None = None
    coordinator: GrowattCoordinator | None = None
    server: WebSocketServer | None = None
    charge_point: GrowattChargePoint | None = None
    polling_task: asyncio.Task | None = None
    startup_check_task: asyncio.Task | None = None
    poll_interval: int | None = None
    poll_interval_schedule: PollIntervalSchedule | None = None
    skip_polling_until: float | None = None
    energy_stop_guard: EnergyStopGuard | None = None
    target_runtime: ChargingTargetRuntime | None = None
    target_handlers: dict[str, Callable[..., Awaitable[Any]]] | None = None
    pv_linkage_profile_handler: Callable[..., Awaitable[None]] | None = None
    append_session_to_csv: Callable[[dict], Awaitable[None]] | None = None
    update_session_events_in_csv: Callable[[str, list], Awaitable[None]] | None = None
    refresh_dashboard: Callable[[], Awaitable[None]] | None = None
    persist_charger_identity: Callable[[str], None] | None = None
    session_history_unsub: Callable[[], None] | None = None
    owns_legacy_history: bool | None = None
    _present: dict[str, None] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self._present.update(
            (item.name, None)
            for item in fields(self)
            if item.name != "_present" and getattr(self, item.name) is not None
        )

    def __setattr__(self, name: str, value: Any) -> None:
        object.__setattr__(self, name, value)
        if name != "_present" and hasattr(self, "_present"):
            self._present[name] = None

    def __getitem__(self, key: str) -> Any:
        if key not in self._present:
            raise KeyError(key)
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        if key == "_present" or key not in self.__slots__:
            raise KeyError(key)
        setattr(self, key, value)

    def __delitem__(self, key: str) -> None:
        if key not in self._present:
            raise KeyError(key)
        object.__setattr__(self, key, None)
        del self._present[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._present)

    def __len__(self) -> int:
        return len(self._present)
