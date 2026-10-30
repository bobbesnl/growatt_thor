"""Execute one logical PV Linkage Apply as explicit physical steps.

The THOR does not offer a transaction that covers all PV Linkage settings.
Manual and Smart Boost therefore require two independent OCPP requests.  This
module keeps the unavoidable partial-success handling outside the Home
Assistant button entity so that the behaviour can be tested directly.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from ocpp.v16.enums import ConfigurationStatus, DataTransferStatus

from ..configuration.writes import ConfigurationWriteStatus
from ..runtime.write_results import (
    ChargerConnectionUnavailable,
    ChargerRequestOutcomeUncertain,
    ChargerWriteResult,
)
from .contracts import PvApplyOwner, PvApplyTransport
from .pv_linkage import (
    ConfigurationWrite,
    DataTransferWrite,
    PvLinkageApplyResult,
    PvLinkageApplyStatus,
    PvLinkageDraft,
)

_LOGGER = logging.getLogger(__name__)


async def apply_pv_linkage_writes(
    *, coordinator, charge_point, draft, writes
) -> ChargerWriteResult:
    """Apply an explicit snapshot; edits made in flight remain pending."""
    return await _PvLinkageApply(coordinator, charge_point, draft, writes).run()


@dataclass(slots=True)
class _PvLinkageApply:
    """Own physical progress for one logical Apply.

    There is deliberately no rollback: after the charger accepts a step, an
    inverse request would be another independently fallible operation. Partial
    or uncertain results retain the draft and request readable state instead.
    """

    coordinator: PvApplyOwner
    charge_point: PvApplyTransport
    draft: PvLinkageDraft
    writes: Sequence[ConfigurationWrite | DataTransferWrite]
    completed_steps: int = 0
    accepted_configuration: bool = False
    active_step: str = "not_started"
    active_configuration_key: str | None = None
    active_configuration_generation: int | None = None

    async def run(self) -> ChargerWriteResult:
        try:
            for write in self.writes:
                if isinstance(write, ConfigurationWrite):
                    failure = await self._apply_configuration(write)
                elif isinstance(write, DataTransferWrite):
                    failure = await self._apply_data_transfer(write)
                else:
                    raise TypeError(f"Unsupported PV Linkage write: {type(write).__name__}")
                if failure is not None:
                    return failure
        except ChargerConnectionUnavailable as exc:
            if self.completed_steps == 0:
                # No acknowledgement: the queue may safely rebind the whole
                # operation to a replacement connection and retry it.
                raise
            return self._connection_lost(exc)
        except ChargerRequestOutcomeUncertain as exc:
            return self._uncertain(exc)
        except Exception as exc:
            # A client/transport error does not prove whether OCPP received it.
            result = self._uncertain(exc)
            _LOGGER.error(
                "Unexpected PV Linkage Apply failure at %s: %s",
                self.active_step,
                exc,
                exc_info=True,
            )
            return result

        outcome = PvLinkageApplyResult.success(len(self.writes))
        self.coordinator.record_pv_linkage_apply_result(outcome)
        # Compare the exact snapshot; never erase newer unsent draft edits.
        self.coordinator.mark_pv_linkage_draft_applied(self.draft)
        if self.accepted_configuration:
            self.coordinator.schedule_configuration_refresh()
        return ChargerWriteResult.success()

    async def _apply_configuration(self, write: ConfigurationWrite) -> ChargerWriteResult | None:
        self.active_step = write.key
        self.active_configuration_key = write.key
        self.active_configuration_generation = self.coordinator.begin_configuration_write(
            write.key,
            write.value,
        )
        result = await self.charge_point.change_configuration(write.key, write.value)
        accepted = result in {ConfigurationStatus.accepted, ConfigurationStatus.reboot_required}
        outcome_is_current = self.coordinator.acknowledge_configuration_write(
            write.key,
            generation=self.active_configuration_generation,
            accepted=accepted,
            result=result,
        )
        if not accepted:
            _LOGGER.error("PV Linkage write %s was rejected: %s", write.key, result)
            return self._rejected(write.key, result)
        if outcome_is_current:
            self.coordinator.update_configuration_value(write.key, write.value)
        self.accepted_configuration = True
        self.completed_steps += 1
        self.active_configuration_key = None
        self.active_configuration_generation = None
        return None

    async def _apply_data_transfer(self, write: DataTransferWrite) -> ChargerWriteResult | None:
        self.active_step = write.message_id
        result = await self.charge_point.send_data_transfer(
            vendor_id=write.vendor_id,
            message_id=write.message_id,
            data=write.data,
        )
        if result != DataTransferStatus.accepted:
            _LOGGER.error("PV Linkage DataTransfer %s was rejected: %s", write.message_id, result)
            return self._rejected(write.message_id, result)
        self.completed_steps += 1
        return None

    def _rejected(self, step: str, result: object) -> ChargerWriteResult:
        outcome = PvLinkageApplyResult.failed(
            completed_steps=self.completed_steps,
            total_steps=len(self.writes),
            failed_step=step,
            reason=result,
        )
        self.coordinator.record_pv_linkage_apply_result(outcome)
        if outcome.status == PvLinkageApplyStatus.PARTIAL:
            # Earlier configuration or DataTransfer steps changed the charger.
            # Re-read every readable key when the queue is idle.
            self.coordinator.schedule_configuration_refresh(delay=0)
            return ChargerWriteResult.partial(f"{step}_rejected", result)
        return ChargerWriteResult.failed(f"{step}_rejected", result)

    def _mark_active_configuration(self, status: ConfigurationWriteStatus, reason: str) -> None:
        if (
            self.active_configuration_key is not None
            and self.active_configuration_generation is not None
        ):
            self.coordinator.mark_configuration_write(
                self.active_configuration_key,
                status,
                generation=self.active_configuration_generation,
                result=reason,
            )

    def _connection_lost(self, exc: Exception) -> ChargerWriteResult:
        self._mark_active_configuration(
            ConfigurationWriteStatus.SKIPPED,
            "compound_aborted_after_partial_apply",
        )
        outcome = PvLinkageApplyResult.failed(
            completed_steps=self.completed_steps,
            total_steps=len(self.writes),
            failed_step=self.active_step,
            reason=exc,
        )
        self.coordinator.record_pv_linkage_apply_result(outcome)
        self.coordinator.schedule_configuration_refresh(delay=0)
        return ChargerWriteResult.partial("connection_lost_after_partial_apply", str(exc))

    def _uncertain(self, exc: Exception) -> ChargerWriteResult:
        self._mark_active_configuration(ConfigurationWriteStatus.UNCERTAIN, str(exc))
        outcome = PvLinkageApplyResult.uncertain(
            completed_steps=self.completed_steps,
            total_steps=len(self.writes),
            failed_step=self.active_step,
            reason=exc,
        )
        self.coordinator.record_pv_linkage_apply_result(outcome)
        self.coordinator.schedule_configuration_refresh(delay=0)
        return ChargerWriteResult.uncertain(str(exc))
