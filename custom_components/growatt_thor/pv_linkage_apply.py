"""Execute one logical PV Linkage Apply as explicit physical steps.

The THOR does not offer a transaction that covers all PV Linkage settings.
Manual and Smart Boost therefore require two independent OCPP requests.  This
module keeps the unavoidable partial-success handling outside the Home
Assistant button entity so that the behaviour can be tested directly.
"""
from __future__ import annotations

import logging

from ocpp.v16.enums import ConfigurationStatus, DataTransferStatus

from .configuration_writes import ConfigurationWriteStatus
from .pv_linkage import (
    ConfigurationWrite,
    DataTransferWrite,
    PvLinkageApplyResult,
    PvLinkageApplyStatus,
)
from .write_queue import (
    ChargerConnectionUnavailable,
    ChargerRequestOutcomeUncertain,
    ChargerWriteResult,
)


_LOGGER = logging.getLogger(__name__)


async def apply_pv_linkage_writes(
    *,
    coordinator,
    charge_point,
    draft,
    writes,
) -> ChargerWriteResult:
    """Apply every physical step and retain an honest logical outcome.

    There is deliberately no rollback here: once the charger accepted one
    OCPP request, sending an inverse request would merely create another
    independently fallible operation.  Instead, partial and uncertain results
    retain the user's draft and trigger a readback of all readable settings.
    """
    total_steps = len(writes)
    completed_steps = 0
    accepted_configuration = False
    active_step = "not_started"
    active_configuration_key = None
    active_configuration_generation = None

    try:
        for write in writes:
            if isinstance(write, ConfigurationWrite):
                active_step = write.key
                active_configuration_key = write.key
                active_configuration_generation = (
                    coordinator.begin_configuration_write(
                        write.key,
                        write.value,
                    )
                )
                result = await charge_point.change_configuration(
                    write.key,
                    write.value,
                )
                accepted = result in {
                    ConfigurationStatus.accepted,
                    ConfigurationStatus.reboot_required,
                }
                outcome_is_current = (
                    coordinator.acknowledge_configuration_write(
                        write.key,
                        generation=active_configuration_generation,
                        accepted=accepted,
                        result=result,
                    )
                )
                if not accepted:
                    _LOGGER.error(
                        "PV Linkage write %s was rejected: %s",
                        write.key,
                        result,
                    )
                    outcome = PvLinkageApplyResult.failed(
                        completed_steps=completed_steps,
                        total_steps=total_steps,
                        failed_step=write.key,
                        reason=result,
                    )
                    coordinator.record_pv_linkage_apply_result(outcome)
                    if outcome.status == PvLinkageApplyStatus.PARTIAL:
                        # At least one earlier step changed the physical
                        # charger. Re-read every readable key once the queue is
                        # idle, even if that earlier step was a DataTransfer.
                        coordinator.schedule_configuration_refresh(delay=0)
                        return ChargerWriteResult.partial(
                            f"{write.key}_rejected",
                            result,
                        )
                    return ChargerWriteResult.failed(
                        f"{write.key}_rejected",
                        result,
                    )
                if outcome_is_current:
                    coordinator.update_configuration_value(
                        write.key,
                        write.value,
                    )
                accepted_configuration = True
                completed_steps += 1
                active_configuration_key = None
                active_configuration_generation = None
                continue

            if isinstance(write, DataTransferWrite):
                active_step = write.message_id
                result = await charge_point.send_data_transfer(
                    vendor_id=write.vendor_id,
                    message_id=write.message_id,
                    data=write.data,
                )
                if result != DataTransferStatus.accepted:
                    _LOGGER.error(
                        "PV Linkage DataTransfer %s was rejected: %s",
                        write.message_id,
                        result,
                    )
                    outcome = PvLinkageApplyResult.failed(
                        completed_steps=completed_steps,
                        total_steps=total_steps,
                        failed_step=write.message_id,
                        reason=result,
                    )
                    coordinator.record_pv_linkage_apply_result(outcome)
                    if outcome.status == PvLinkageApplyStatus.PARTIAL:
                        coordinator.schedule_configuration_refresh(delay=0)
                        return ChargerWriteResult.partial(
                            f"{write.message_id}_rejected",
                            result,
                        )
                    return ChargerWriteResult.failed(
                        f"{write.message_id}_rejected",
                        result,
                    )
                completed_steps += 1
                continue

            raise TypeError(
                f"Unsupported PV Linkage write: {type(write).__name__}"
            )
    except ChargerConnectionUnavailable as exc:
        if completed_steps == 0:
            # No step was acknowledged, so the queue can safely rebind the
            # whole operation to a new connection and retry it.
            raise
        if (
            active_configuration_key is not None
            and active_configuration_generation is not None
        ):
            coordinator.mark_configuration_write(
                active_configuration_key,
                ConfigurationWriteStatus.SKIPPED,
                generation=active_configuration_generation,
                result="compound_aborted_after_partial_apply",
            )
        outcome = PvLinkageApplyResult.failed(
            completed_steps=completed_steps,
            total_steps=total_steps,
            failed_step=active_step,
            reason=exc,
        )
        coordinator.record_pv_linkage_apply_result(outcome)
        coordinator.schedule_configuration_refresh(delay=0)
        return ChargerWriteResult.partial(
            "connection_lost_after_partial_apply",
            str(exc),
        )
    except ChargerRequestOutcomeUncertain as exc:
        if (
            active_configuration_key is not None
            and active_configuration_generation is not None
        ):
            coordinator.mark_configuration_write(
                active_configuration_key,
                ConfigurationWriteStatus.UNCERTAIN,
                generation=active_configuration_generation,
                result=str(exc),
            )
        outcome = PvLinkageApplyResult.uncertain(
            completed_steps=completed_steps,
            total_steps=total_steps,
            failed_step=active_step,
            reason=exc,
        )
        coordinator.record_pv_linkage_apply_result(outcome)
        coordinator.schedule_configuration_refresh(delay=0)
        return ChargerWriteResult.uncertain(str(exc))
    except Exception as exc:
        # An unexpected transport/client failure does not prove whether the
        # active request reached the charger. Preserve the draft and reconcile
        # readable state instead of labelling the operation as rejected.
        if (
            active_configuration_key is not None
            and active_configuration_generation is not None
        ):
            coordinator.mark_configuration_write(
                active_configuration_key,
                ConfigurationWriteStatus.UNCERTAIN,
                generation=active_configuration_generation,
                result=str(exc),
            )
        outcome = PvLinkageApplyResult.uncertain(
            completed_steps=completed_steps,
            total_steps=total_steps,
            failed_step=active_step,
            reason=exc,
        )
        coordinator.record_pv_linkage_apply_result(outcome)
        coordinator.schedule_configuration_refresh(delay=0)
        _LOGGER.error(
            "Unexpected PV Linkage Apply failure at %s: %s",
            active_step,
            exc,
            exc_info=True,
        )
        return ChargerWriteResult.uncertain(str(exc))

    outcome = PvLinkageApplyResult.success(total_steps)
    coordinator.record_pv_linkage_apply_result(outcome)
    # The coordinator compares the current draft with this exact snapshot.
    # Edits made while Apply was in flight must remain visibly pending.
    coordinator.mark_pv_linkage_draft_applied(draft)
    if accepted_configuration:
        coordinator.schedule_configuration_refresh()
    return ChargerWriteResult.success()
