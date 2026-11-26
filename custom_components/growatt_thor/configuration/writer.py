"""Compose one ChangeConfiguration write flow from a per-entity policy.

Every writable configuration entity follows the same skeleton: check the
request, record the intent, queue one callback, then classify the charger's
answer. The differences between entities (validation, encoding, accepted-state
order, rollback and exception boundary) are intentional and documented in
docs/invariants.md. They live in a ``WritePolicy``; the ``ConfigurationWriter``
owns the order of the shared steps so an entity cannot reorder them by accident.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ocpp.v16.enums import ConfigurationStatus

from ..runtime.action_errors import (
    async_require_command_completion,
    raise_charger_disconnected,
    raise_write_blocked,
)
from ..runtime.keys import ACTIVE_CHARGE_POINT
from ..runtime.write_results import (
    CONFIGURATION_WRITE_POLICY,
    ChargerConnectionUnavailable,
    ChargerRequestOutcomeUncertain,
    ChargerWriteResult,
)
from .writes import ConfigurationWriteStatus

if TYPE_CHECKING:
    from ..runtime.write_results import ChargerCommandHandle
    from .contracts import ConfigurationTransport, ConfigurationWriteOwner

_LOGGER = logging.getLogger(__name__)

ACCEPTED_CONFIGURATION_RESULTS = frozenset(
    {ConfigurationStatus.accepted, ConfigurationStatus.reboot_required}
)


@dataclass(frozen=True, slots=True)
class ConfigurationWrite[ValueT]:
    """One queued intent: the wire payload plus what the entity needs back.

    ``value`` is the domain value the entity mirrors after acceptance;
    ``previous`` is the policy's rollback token from ``apply_optimistic``.
    """

    key: str
    raw_value: str
    value: ValueT
    generation: int
    previous: object = None


class WritePolicy[ValueT]:
    """Entity-specific decisions around the shared configuration write flow.

    The defaults describe a plain configuration control: no optimistic state,
    readback after acceptance, and a transport-only exception boundary.
    """

    #: Coalesces queued writes; None uses the configuration key.
    dedupe_key: str | None = None
    #: True: unexpected errors after sending (acknowledgement, accepted state)
    #: are handled by ``on_unexpected`` like transport errors.
    guards_outcome = False
    #: True: ``apply_accepted`` schedules the readback itself for a current
    #: outcome, so the writer schedules it only for a superseded one.
    refreshes_on_apply = False

    def __init__(self, owner: ConfigurationWriteOwner) -> None:
        self.owner = owner

    @property
    def label(self) -> str:
        """Name used in request-time log messages."""
        raise NotImplementedError

    def encode(self, value: ValueT) -> tuple[str, str]:
        """Return the configuration key and the OCPP wire string."""
        raise NotImplementedError

    def request_block_reason(self) -> str | None:
        """Why an HA action must be refused now, or None."""
        raise NotImplementedError

    def queued_block_reason(self, write: ConfigurationWrite[ValueT]) -> str | None:
        """Revalidated inside the queue callback immediately before sending."""
        return self.request_block_reason()

    def is_unchanged(self, value: ValueT) -> bool:
        """Return True when the request needs no write."""
        return False

    def apply_optimistic(self, value: ValueT) -> object:
        """Publish local state before queueing and return the rollback token."""
        return None

    def on_skipped(self, write: ConfigurationWrite[ValueT], reason: str) -> None:
        """Called after a queued write was marked skipped before sending."""

    def on_unsent(self, write: ConfigurationWrite[ValueT]) -> None:
        """Called when the queue replaced, cancelled or expired the write."""

    def apply_accepted(self, write: ConfigurationWrite[ValueT]) -> None:
        """Apply reported state; called only for the current outcome."""
        self.owner.update_configuration_value(write.key, write.raw_value)

    def schedule_readback(self, write: ConfigurationWrite[ValueT], *, delay: float | None) -> None:
        """Read the configuration back; None keeps the coordinator's spacing."""
        if delay is None:
            self.owner.schedule_configuration_refresh()
        else:
            self.owner.schedule_configuration_refresh(delay=delay)

    def report_accepted(self, write: ConfigurationWrite[ValueT], result: object) -> None:
        if result == ConfigurationStatus.reboot_required:
            _LOGGER.warning("%s accepted but requires a charger reboot", write.key)

    def on_rejected(self, write: ConfigurationWrite[ValueT], result: object) -> None:
        _LOGGER.error("%s change rejected by charger: %s", write.key, result)

    def on_unexpected(
        self, write: ConfigurationWrite[ValueT], exc: Exception
    ) -> ChargerWriteResult | None:
        """Return a terminal result, or None to let the queue classify ``exc``."""
        return None


class ConfigurationWriter[ValueT]:
    """Run one entity's configuration writes through the coordinator queue."""

    __slots__ = ("_owner", "_policy")

    def __init__(self, owner: ConfigurationWriteOwner, policy: WritePolicy[ValueT]) -> None:
        self._owner = owner
        self._policy = policy

    def require_charge_point(self) -> ConfigurationTransport:
        """Raise the public action error when no write may be queued now."""
        label = self._policy.label
        if (block_reason := self._policy.request_block_reason()) is not None:
            _LOGGER.warning("Cannot change %s: %s", label, block_reason)
            # Entity methods are HA action handlers. Raising here makes a
            # blocked automation visible in its trace instead of reporting a
            # successful call for a command that was never queued.
            raise_write_blocked(block_reason)
        charge_point: ConfigurationTransport | None = self._owner.runtime_data.get(
            ACTIVE_CHARGE_POINT
        )
        if not charge_point:
            _LOGGER.warning("Cannot change %s: charger not connected", label)
            raise_charger_disconnected()
        return charge_point

    async def async_request(self, value: ValueT) -> None:
        """Handle one HA action and wait for the bounded queue outcome."""
        charge_point = self.require_charge_point()
        if self._policy.is_unchanged(value):
            return
        previous = self._policy.apply_optimistic(value)
        handle = await self.async_enqueue(charge_point, value, previous=previous)
        await async_require_command_completion(handle)

    async def async_enqueue(
        self,
        charge_point: ConfigurationTransport,
        value: ValueT,
        *,
        previous: object = None,
    ) -> ChargerCommandHandle:
        """Record the intent and queue it without waiting for completion."""
        key, raw_value = self._policy.encode(value)
        # Record the desired value while it is still waiting in the queue. It
        # remains separate from configuration_values, which always represents
        # the last value reported or acknowledged by the THOR.
        generation = self._owner.begin_configuration_write(key, raw_value)
        write = ConfigurationWrite(key, raw_value, value, generation, previous)

        def on_unsent(_result: ChargerWriteResult) -> None:
            self._policy.on_unsent(write)

        return await self._owner.queue_write(
            self._execute,
            charge_point,
            write,
            dedupe_key=self._policy.dedupe_key or key,
            command_name=f"ChangeConfiguration({key})",
            requires_connection=True,
            configuration_key=key,
            configuration_generation=generation,
            policy=CONFIGURATION_WRITE_POLICY,
            on_unsent=on_unsent,
        )

    async def _execute(
        self, charge_point: ConfigurationTransport, write: ConfigurationWrite[ValueT]
    ) -> ChargerWriteResult:
        """Queue callback: the only place this entity's write reaches the wire."""
        policy = self._policy
        if (reason := policy.queued_block_reason(write)) is not None:
            self._owner.mark_configuration_write(
                write.key,
                ConfigurationWriteStatus.SKIPPED,
                generation=write.generation,
                result=reason,
            )
            policy.on_skipped(write, reason)
            return ChargerWriteResult.skipped(reason)
        try:
            result = await charge_point.change_configuration(write.key, write.raw_value)
            if policy.guards_outcome:
                return self._complete(write, result)
        except ChargerConnectionUnavailable:
            # The queue can safely rebind and retry because no request reached
            # the OCPP layer.
            raise
        except ChargerRequestOutcomeUncertain as exc:
            self._owner.mark_configuration_write(
                write.key,
                ConfigurationWriteStatus.UNCERTAIN,
                generation=write.generation,
                result=str(exc),
            )
            policy.schedule_readback(write, delay=0)
            return ChargerWriteResult.uncertain(str(exc))
        except Exception as exc:
            handled = policy.on_unexpected(write, exc)
            if handled is None:
                raise
            return handled
        return self._complete(write, result)

    def _complete(self, write: ConfigurationWrite[ValueT], result: object) -> ChargerWriteResult:
        policy = self._policy
        accepted = result in ACCEPTED_CONFIGURATION_RESULTS
        # Example: 10 A was sent, then 16 A was requested before its reply.
        # The 10 A acknowledgement is real, but cannot confirm the newer intent.
        current = self._owner.acknowledge_configuration_write(
            write.key, generation=write.generation, accepted=accepted, result=result
        )
        if not accepted:
            policy.on_rejected(write, result)
            return ChargerWriteResult.failed("charger_rejected", result)
        # The charger may accept an older request after a newer automation has
        # already queued its replacement. Keep the accepted physical outcome for
        # readback, but expose only the newest intent in HA.
        if current:
            policy.apply_accepted(write)
        if not (policy.refreshes_on_apply and current):
            policy.schedule_readback(write, delay=None)
        policy.report_accepted(write, result)
        return ChargerWriteResult.success(result)
