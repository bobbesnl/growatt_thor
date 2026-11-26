"""On/off views of the charger snapshot for automations.

Each sensor derives its state from ``ChargerSnapshot`` only, so it agrees with
the Status sensor and the card. A status that says nothing reliable (no
connection yet, Reserved, Unavailable, the local Idle) stays unknown instead of
being guessed as off.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory

from .charging.snapshot import ChargerSnapshot, VehicleState, charger_snapshot
from .entity import ThorEntity

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import GrowattCoordinator
    from .runtime.entry import ThorConfigEntry

_PLUGGED_IN = {
    VehicleState.CONNECTED: True,
    VehicleState.CHARGING: True,
    VehicleState.DISCONNECTED: False,
}


def _status_known(snapshot: ChargerSnapshot) -> bool:
    return snapshot.connected and snapshot.status is not None


@dataclass(frozen=True, kw_only=True)
class ThorBinarySensorDescription(BinarySensorEntityDescription):
    """Declare a binary sensor's state and availability from the snapshot."""

    is_on_fn: Callable[[ChargerSnapshot], bool | None]
    available_fn: Callable[[ChargerSnapshot], bool] = _status_known


BINARY_SENSOR_DESCRIPTIONS: tuple[ThorBinarySensorDescription, ...] = (
    ThorBinarySensorDescription(
        key="vehicle_connected",
        translation_key="vehicle_connected",
        device_class=BinarySensorDeviceClass.PLUG,
        # Faulted and the ambiguous statuses do not tell whether a car is plugged in.
        is_on_fn=lambda snapshot: _PLUGGED_IN.get(snapshot.vehicle_state),
    ),
    ThorBinarySensorDescription(
        key="charging",
        translation_key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        is_on_fn=lambda snapshot: snapshot.status == "charging",
    ),
    ThorBinarySensorDescription(
        key="charger_fault",
        translation_key="charger_fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda snapshot: snapshot.faulted,
    ),
    ThorBinarySensorDescription(
        key="charger_connected",
        translation_key="charger_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda snapshot: snapshot.connected,
        # The connection itself is always known while the entry is loaded.
        available_fn=lambda snapshot: True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ThorConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    # HA forwards platforms only after this entry has claimed its coordinator.
    coordinator = cast("GrowattCoordinator", entry.runtime_data.coordinator)
    async_add_entities(
        ThorBinarySensor(coordinator, entry, description)
        for description in BINARY_SENSOR_DESCRIPTIONS
    )


class ThorBinarySensor(ThorEntity, BinarySensorEntity):
    """Project one snapshot predicate into HA."""

    entity_description: ThorBinarySensorDescription

    def __init__(
        self,
        coordinator: GrowattCoordinator,
        entry: ConfigEntry,
        description: ThorBinarySensorDescription,
    ) -> None:
        self.entity_description = description
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        snapshot = charger_snapshot(self.coordinator)
        if not self.entity_description.available_fn(snapshot):
            return None
        return self.entity_description.is_on_fn(snapshot)

    @property
    def available(self) -> bool:
        return super().available and self.entity_description.available_fn(
            charger_snapshot(self.coordinator)
        )
