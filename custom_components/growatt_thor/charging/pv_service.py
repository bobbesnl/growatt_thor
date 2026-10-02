"""One resilient service boundary for the guided PV Linkage profile dialog."""
from __future__ import annotations

from datetime import time
import logging

import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from ..runtime.action_errors import (
    async_require_command_completion,
    raise_action_validation,
    raise_write_blocked,
)
from ..const import DOMAIN
from .pv_linkage import (
    PvBoostMode,
    PvLinkageDraft,
    PvLinkageProfile,
    build_pv_linkage_profile_writes,
    profile_validation_errors,
)
from .pv_apply import apply_pv_linkage_writes
from ..runtime.write_queue import CONFIGURATION_WRITE_POLICY, ChargerWriteResult

_LOGGER = logging.getLogger(__name__)
SERVICE = "apply_pv_linkage_profile"


def _optional_time(value: object) -> time | None:
    if value in (None, ""):
        return None
    try:
        return time.fromisoformat(str(value))
    except ValueError:
        raise vol.Invalid("Expected an HH:MM time") from None


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise vol.Invalid("Expected a number") from None


SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): str,
        vol.Required("working_mode"): vol.In(["pv_linkage", "pv_linkage_plus"]),
        vol.Optional("grid_import_limit_kw"): _optional_float,
        vol.Required("boost_mode"): vol.In([mode.value for mode in PvBoostMode]),
        vol.Optional("manual_start"): _optional_time,
        vol.Optional("manual_end"): _optional_time,
        vol.Optional("smart_finish"): _optional_time,
        vol.Optional("smart_target_energy_kwh"): _optional_float,
    }
)


def _profile(data: dict) -> PvLinkageProfile:
    return PvLinkageProfile(
        working_mode=data["working_mode"],
        grid_import_limit_kw=data.get("grid_import_limit_kw"),
        boost=PvLinkageDraft(
            boost_mode=PvBoostMode(data["boost_mode"]),
            manual_start=data.get("manual_start"),
            manual_end=data.get("manual_end"),
            smart_finish=data.get("smart_finish"),
            smart_target_energy_kwh=data.get("smart_target_energy_kwh"),
        ),
    )


def _block_reason(hass, coordinator, writes) -> str | None:
    charge_point = hass.data.get(DOMAIN, {}).get("charge_point")
    if not coordinator.connected or charge_point is None:
        return "charger_disconnected"
    if coordinator.charger_is_faulted:
        return "charger_faulted"
    if coordinator.transaction_is_active:
        return "active_transaction"
    if not coordinator.external_meter_ready_for_pv:
        return "external_meter_not_ready"
    for write in writes:
        key = getattr(write, "key", None)
        reported = coordinator.configuration_values.get(key)
        if reported is not None and reported.readonly is True:
            return "configuration_read_only"
    return None


def async_register_pv_linkage_service(hass) -> None:
    """Register the public action independently from config-entry reloads."""
    if hass.services.has_service(DOMAIN, SERVICE):
        return

    async def dispatch(call):
        handler = hass.data.get(DOMAIN, {}).get("pv_linkage_profile_handler")
        if handler is None:
            raise HomeAssistantError("growatt_thor_entry_not_loaded")
        return await handler(call)

    hass.services.async_register(DOMAIN, SERVICE, dispatch, schema=SERVICE_SCHEMA)


async def async_setup_pv_linkage_service(hass, entry, coordinator) -> None:
    """Bind the registered service to the active single-charger runtime."""

    async def handle(call):
        if call.data["entry_id"] != entry.entry_id:
            raise_action_validation(
                "action_not_allowed",
                placeholders={"reason": "config_entry_mismatch"},
            )
        profile = _profile(call.data)
        if errors := profile_validation_errors(profile):
            raise_action_validation(
                "invalid_pv_linkage_draft",
                placeholders={"errors": ", ".join(errors)},
            )
        writes = build_pv_linkage_profile_writes(profile, now=dt_util.now())
        if reason := _block_reason(hass, coordinator, writes):
            if reason == "external_meter_not_ready":
                raise_action_validation(
                    "external_meter_not_ready",
                    placeholders={"option": profile.working_mode},
                )
            raise_write_blocked(reason)

        draft = profile.boost
        coordinator.update_pv_linkage_draft(
            pv_boost_mode_draft=draft.boost_mode,
            pv_manual_start_draft=draft.manual_start,
            pv_manual_end_draft=draft.manual_end,
            pv_smart_finish_draft=draft.smart_finish,
            pv_smart_target_energy_draft=draft.smart_target_energy_kwh,
        )
        charge_point = hass.data[DOMAIN]["charge_point"]

        async def apply(current_charge_point, expected_draft, expected_writes):
            if reason := _block_reason(hass, coordinator, expected_writes):
                _LOGGER.warning("Skipping queued PV Linkage profile: %s", reason)
                return ChargerWriteResult.skipped(reason)
            return await apply_pv_linkage_writes(
                coordinator=coordinator,
                charge_point=current_charge_point,
                draft=expected_draft,
                writes=expected_writes,
            )

        handle = await coordinator.queue_write(
            apply,
            charge_point,
            draft,
            writes,
            dedupe_key="pv_linkage_profile",
            command_name="ApplyPvLinkageProfile",
            requires_connection=True,
            policy=CONFIGURATION_WRITE_POLICY,
        )
        await async_require_command_completion(handle)

    hass.data[DOMAIN]["pv_linkage_profile_handler"] = handle


def async_unload_pv_linkage_service(hass) -> None:
    """Detach only the current entry handler; keep the action registered."""
    hass.data.get(DOMAIN, {}).pop("pv_linkage_profile_handler", None)
