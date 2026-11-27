"""One resilient service boundary for the guided PV Linkage profile dialog."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from datetime import time
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from ..coerce import optional_float
from ..const import DOMAIN
from ..runtime.action_errors import (
    async_require_command_completion,
    raise_action_validation,
    raise_write_blocked,
)
from ..runtime.keys import ACTIVE_CHARGE_POINT, PV_LINKAGE_PROFILE_HANDLER
from ..runtime.ownership import entry_runtime_data
from ..runtime.write_results import (
    CONFIGURATION_WRITE_POLICY,
    ChargerCommandResult,
    ChargerConnectionUnavailable,
    ChargerWriteResult,
    ChargerWriteStatus,
)
from .contracts import PvApplyTransport, PvServiceOwner
from .control_capabilities import selected_working_mode
from .pv_apply import apply_pv_linkage_writes
from .pv_draft import PvProfileApplyProgress
from .pv_linkage import (
    ConfigurationWrite,
    DataTransferWrite,
    PvBoostMode,
    PvLinkageDraft,
    PvLinkageProfile,
    build_pv_linkage_profile_writes,
    profile_validation_errors,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant, ServiceCall

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
    number = optional_float(value, finite=False)
    if number is None:
        raise vol.Invalid("Expected a number")
    return number


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


def _profile(data: Mapping[str, Any]) -> PvLinkageProfile:
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


def _block_reason(
    coordinator: PvServiceOwner,
    writes: Sequence[ConfigurationWrite | DataTransferWrite],
) -> str | None:
    charge_point = coordinator.runtime_data.get(ACTIVE_CHARGE_POINT)
    if not coordinator.connected or charge_point is None:
        return "charger_disconnected"
    if coordinator.charger_reboot_pending:
        return "charger_rebooting"
    if coordinator.charger_is_faulted:
        return "charger_faulted"
    if coordinator.transaction_is_active:
        return "active_transaction"
    if not coordinator.external_meter.ready_for_pv:
        return "external_meter_not_ready"
    for write in writes:
        key = getattr(write, "key", None)
        reported = coordinator.configuration_values.get(key) if key is not None else None
        if reported is not None and reported.readonly is True:
            return "configuration_read_only"
    return None


def async_register_pv_linkage_service(hass: HomeAssistant) -> None:
    """Register the public action independently from config-entry reloads."""
    if hass.services.has_service(DOMAIN, SERVICE):
        return

    async def dispatch(call: ServiceCall) -> None:
        runtime = entry_runtime_data(hass.data.get(DOMAIN, {}), call.data["entry_id"]) or {}
        handler = runtime.get(PV_LINKAGE_PROFILE_HANDLER)
        if handler is None:
            raise HomeAssistantError("growatt_thor_entry_not_loaded")
        return await cast("Callable[[ServiceCall], Awaitable[None]]", handler)(call)

    hass.services.async_register(DOMAIN, SERVICE, dispatch, schema=SERVICE_SCHEMA)


async def async_setup_pv_linkage_service(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: PvServiceOwner
) -> None:
    """Bind the registered service to the entry's runtime."""

    async def handle(call: ServiceCall) -> None:
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
        if reason := _block_reason(coordinator, writes):
            if reason == "external_meter_not_ready":
                raise_action_validation(
                    "external_meter_not_ready",
                    placeholders={"option": profile.working_mode},
                )
            raise_write_blocked(reason)

        draft = profile.boost
        coordinator.update_pv_linkage_draft(
            boost_mode=draft.boost_mode,
            manual_start=draft.manual_start,
            manual_end=draft.manual_end,
            smart_finish=draft.smart_finish,
            smart_target_energy_kwh=draft.smart_target_energy_kwh,
        )
        charge_point = coordinator.runtime_data[ACTIVE_CHARGE_POINT]
        progress = PvProfileApplyProgress(
            request_id=uuid4().hex,
            working_mode=profile.working_mode,
            status="queued",
            completed_steps=0,
            total_steps=len(writes),
            updated_at=coordinator.now(),
        )
        coordinator.pv_draft.profile_apply = progress
        coordinator.async_set_updated_data(True)

        def publish(status: str, completed_steps: int | None = None) -> None:
            nonlocal progress
            if coordinator.pv_draft.profile_apply is not progress:
                # A newer profile can replace this request while it is in flight.
                return
            progress = replace(
                progress,
                status=status,
                completed_steps=progress.completed_steps
                if completed_steps is None
                else completed_steps,
                updated_at=coordinator.now(),
            )
            coordinator.pv_draft.profile_apply = progress
            coordinator.async_set_updated_data(True)

        async def apply(
            current_charge_point: PvApplyTransport,
            expected_draft: PvLinkageDraft,
            expected_writes: Sequence[ConfigurationWrite | DataTransferWrite],
        ) -> ChargerWriteResult:
            if reason := _block_reason(coordinator, expected_writes):
                _LOGGER.warning("Skipping queued PV Linkage profile: %s", reason)
                return ChargerWriteResult.skipped(reason)
            publish("applying", 0)
            try:
                return await apply_pv_linkage_writes(
                    coordinator=coordinator,
                    charge_point=current_charge_point,
                    draft=expected_draft,
                    writes=expected_writes,
                    on_step_accepted=lambda count: publish("applying", count),
                )
            except ChargerConnectionUnavailable:
                # No step reached the wallbox. The queue may retry on reconnect.
                publish("queued", 0)
                raise

        try:
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
        except BaseException:
            publish("skipped")
            raise

        def complete(result: ChargerCommandResult) -> None:
            status = result.write_status.value
            if (
                result.write_status == ChargerWriteStatus.SUCCESS
                and selected_working_mode(coordinator.configuration_values) != profile.working_mode
            ):
                status = "awaiting_mode"
            publish(status)

        handle.add_done_callback(complete)
        await async_require_command_completion(handle)

    coordinator.runtime_data[PV_LINKAGE_PROFILE_HANDLER] = handle


def async_unload_pv_linkage_service(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Detach only the current entry handler; keep the action registered."""
    runtime = entry_runtime_data(hass.data.get(DOMAIN, {}), entry.entry_id)
    if runtime is not None:
        runtime.pop(PV_LINKAGE_PROFILE_HANDLER, None)
