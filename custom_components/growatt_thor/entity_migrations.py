"""One-time Home Assistant entity-registry migrations."""
from __future__ import annotations

from .const import DOMAIN

LEGACY_SESSION_DURATION_UNIT_MIGRATION = "_migrate_session_duration_unit"
PENDING_EXTERNAL_METER_READBACK_MIGRATION = (
    "_migrate_external_meter_readbacks"
)
REDUNDANT_EXTERNAL_METER_READBACK_SUFFIXES = (
    "external_meter_external_sampling_wiring",
    "external_meter_power_meter_type",
    "external_meter_power_meter_address",
)


def migrate_session_duration_unit(registry, entry_id: str) -> bool:
    """Replace the legacy minute display override with hours once."""
    unique_id = f"{entry_id}_last_session_duration"
    entity_id = registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        unique_id,
    )
    entity = registry.async_get(entity_id) if entity_id is not None else None
    if entity is None:
        return False

    private_sensor_options = dict(entity.options.get("sensor.private", {}))
    legacy_unit = (
        entity.unit_of_measurement == "min"
        or private_sensor_options.get("suggested_unit_of_measurement") == "min"
    )
    if not legacy_unit:
        return False

    private_sensor_options["suggested_unit_of_measurement"] = "h"
    sensor_options = dict(entity.options.get("sensor", {}))
    sensor_options["suggested_display_precision"] = 2

    registry.async_update_entity_options(
        entity.entity_id,
        "sensor.private",
        private_sensor_options,
    )
    registry.async_update_entity_options(
        entity.entity_id,
        "sensor",
        sensor_options,
    )
    registry.async_update_entity(
        entity.entity_id,
        unit_of_measurement="h",
    )
    return True


def disable_redundant_external_meter_readbacks(
    registry,
    entry_id: str,
    disabled_by,
) -> tuple[str, ...]:
    """Disable readback sensors replaced by External Meter controls."""
    disabled = []
    for suffix in REDUNDANT_EXTERNAL_METER_READBACK_SUFFIXES:
        entity_id = registry.async_get_entity_id(
            "sensor",
            DOMAIN,
            f"{entry_id}_{suffix}",
        )
        entity = registry.async_get(entity_id) if entity_id is not None else None
        if entity is None or entity.disabled_by is not None:
            continue
        registry.async_update_entity(entity_id, disabled_by=disabled_by)
        disabled.append(entity_id)
    return tuple(disabled)
