"""Own charger write execution, expiry and completion independently of observations."""
from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import logging
from typing import Any, Protocol

from ..configuration.writes import ConfigurationWriteStatus
from .write_queue import (
    ChargerCommandHandle, ChargerCommandResult, ChargerConnectionUnavailable,
    ChargerRequestOutcomeUncertain, ChargerWriteQueuePolicy,
    ChargerWriteReconnectPolicy, ChargerWriteResult, ChargerWriteStatus,
    DEFAULT_WRITE_POLICY, create_command_handle,
)

_LOGGER = logging.getLogger(__name__)


class WriteQueueOwner(Protocol):
    """Observation and publication boundary; never a second queue owner."""
    hass: Any
    runtime_data: Mapping[str, Any]
    connected: bool

    def now(self) -> str: ...
    def pause_polling_until(self, until: float) -> None: ...
    def mark_configuration_write(self, key: str, status: ConfigurationWriteStatus,
                                 *, generation: int, result: str | None = None) -> bool: ...
    def schedule_configuration_refresh(self, *, delay: float = 20.0) -> Any: ...
    def publish_write_result(self, result: ChargerCommandResult) -> None: ...


@dataclass(slots=True)
class ChargerWriteItem:
    func: Callable[..., Awaitable[Any]]
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    enqueued_at: float
    queued_at: str
    expires_at: float
    dedupe_key: object | None
    priority: bool
    rate_limited: bool
    command_name: str
    requires_connection: bool
    configuration_key: str | None
    configuration_generation: int | None
    policy: ChargerWriteQueuePolicy
    revalidate: Callable[[], str | None] | None
    on_unsent: Callable[[ChargerWriteResult], None] | None
    command_id: str
    completion: asyncio.Future[ChargerCommandResult]
    terminal_result: ChargerCommandResult | None = None


class ChargerWriteQueue:
    """One write owner per charger; lifetimes and spacing use a monotonic clock."""

    def __init__(self, owner: WriteQueueOwner, connection_changed: asyncio.Event) -> None:
        self.owner = owner
        self.connection_changed = connection_changed
        self._pending: deque[ChargerWriteItem] = deque()
        self._lock = asyncio.Lock()
        self._changed = asyncio.Event()
        self.idle = asyncio.Event()
        self.idle.set()
        self.task: asyncio.Task | None = None
        self._active: ChargerWriteItem | None = None
        self._closing = False
        self._last_write_monotonic: float | None = None
        self.min_write_interval = 20.0
        self.poll_pause_after_write = 20.0
        self.last_result: ChargerCommandResult | None = None

    def begin_shutdown(self) -> None:
        self._closing = True
        if self.task is not None and not self.task.done():
            self.task.cancel()

    async def async_shutdown(self) -> None:
        self.begin_shutdown()
        task = self.task
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass
        while self._pending:
            self._finish_unsent_write(self._pending.popleft(), ChargerWriteResult.skipped("integration_unloaded"))
        self.idle.set()

    async def enqueue(
        self,
        write_func,
        *args,
        dedupe_key=None,
        priority=False,
        rate_limited=True,
        command_name=None,
        requires_connection=False,
        configuration_key=None,
        configuration_generation=None,
        policy: ChargerWriteQueuePolicy = DEFAULT_WRITE_POLICY,
        revalidate=None,
        on_unsent=None,
        **kwargs,
    ) -> ChargerCommandHandle:
        """Queue a charger command with optional deduplication and priority.

        ``requires_connection`` means that the first positional argument is a
        charge-point object.  We replace that object with the current
        connection immediately before execution.  This is intentionally
        explicit: queued work may wait for tens of seconds, during which the
        THOR can reconnect and make the originally captured object stale.

        ``policy`` bounds how long an unsent intent remains valid and whether
        it may cross a disconnect. ``revalidate`` returns a skip reason when
        runtime state has changed. ``on_unsent`` restores entity-local
        optimistic state for replaced, skipped, or expired queue entries. The
        returned handle identifies this exact intent and resolves once with
        its terminal physical or local outcome.
        """
        if requires_connection and not args:
            raise ValueError("A connection-bound write requires a charge point argument")
        if (configuration_key is None) != (configuration_generation is None):
            raise ValueError(
                "Configuration key and generation must be queued together"
            )

        # Queue lifetimes use the monotonic loop clock: correcting the wall clock
        # must not extend an old intent. UTC timestamps below are for diagnostics.
        enqueued_at = self.owner.hass.loop.time()
        handle = create_command_handle()
        write_item = ChargerWriteItem(
            func=write_func,
            args=args,
            kwargs=kwargs,
            enqueued_at=enqueued_at,
            queued_at=self.owner.now(),
            expires_at=enqueued_at + policy.expires_after,
            dedupe_key=dedupe_key,
            priority=priority,
            rate_limited=rate_limited,
            command_name=command_name or write_func.__name__,
            requires_connection=requires_connection,
            configuration_key=configuration_key,
            configuration_generation=configuration_generation,
            policy=policy,
            revalidate=revalidate,
            on_unsent=on_unsent,
            command_id=handle.command_id,
            completion=handle._completion,
        )

        if self._closing:
            # A late background callback can race integration unload.  Return
            # a normal, already resolved handle instead of creating an orphan
            # Future or silently accepting work that can never execute.
            self._finish_unsent_write(
                write_item,
                ChargerWriteResult.skipped("integration_unloaded"),
            )
            return handle

        if dedupe_key is not None:
            retained_items = deque()
            for item in self._pending:
                if item.dedupe_key == dedupe_key:
                    # The replacement's generation is already current. Marking
                    # the old item now records a superseded diagnostic without
                    # allowing its cleanup callback to touch the newer intent.
                    self._finish_unsent_write(
                        item,
                        ChargerWriteResult.skipped(
                            "replaced_by_newer_intent"
                        ),
                    )
                else:
                    retained_items.append(item)
            self._pending = retained_items

        if priority:
            insert_at = next(
                (
                    index
                    for index, item in enumerate(self._pending)
                    if not item.priority
                ),
                len(self._pending),
            )
            self._pending.insert(insert_at, write_item)
        else:
            self._pending.append(write_item)

        _LOGGER.debug(
            "📥 Queued %s [%s]. Queue size: %d",
            write_item.command_name,
            write_item.command_id,
            len(self._pending),
        )
        self.idle.clear()
        self._changed.set()

        if self.task is None or self.task.done():
            self.task = self.owner.hass.async_create_task(self._process_write_queue())
        return handle

    async def _process_write_queue(self):
        """Process writes without losing them across a charger reconnect."""
        async with self._lock:
            try:
                while self._pending:
                    write_item = self._pending[0]

                    if self._write_item_is_expired(write_item):
                        self._pending.popleft()
                        self._finish_unsent_write(
                            write_item,
                            ChargerWriteResult.expired(),
                        )
                        continue

                    invalid_reason = self._write_revalidation_failure(write_item)
                    if invalid_reason is not None:
                        self._pending.popleft()
                        self._finish_unsent_write(
                            write_item,
                            ChargerWriteResult.skipped(invalid_reason),
                        )
                        continue

                    if write_item.requires_connection:
                        charge_point = self.owner.runtime_data.get(
                            "charge_point"
                        )
                        if charge_point is None or not self.owner.connected:
                            if (
                                write_item.policy.reconnect
                                == ChargerWriteReconnectPolicy.DISCARD_WHEN_DISCONNECTED
                            ):
                                self._pending.popleft()
                                self._finish_unsent_write(
                                    write_item,
                                    ChargerWriteResult.expired(
                                        "discarded_on_disconnect"
                                    ),
                                )
                                continue
                            # Do not pop an unsent command while disconnected.
                            # A later write with the same dedupe key can still
                            # replace it, preserving last-value-wins semantics.
                            _LOGGER.info(
                                "⏸️ Waiting for reconnect before %s",
                                write_item.command_name,
                            )
                            self.connection_changed.clear()
                            charge_point = self.owner.runtime_data.get(
                                "charge_point"
                            )
                            if charge_point is None or not self.owner.connected:
                                try:
                                    await asyncio.wait_for(
                                        self.connection_changed.wait(),
                                        timeout=self._write_expiry_remaining(
                                            write_item
                                        ),
                                    )
                                except asyncio.TimeoutError:
                                    # The next loop iteration records the
                                    # terminal expired result without sending.
                                    pass
                            continue

                    if (
                        write_item.rate_limited
                        and self._last_write_monotonic is not None
                    ):
                        time_since_last = (
                            self.owner.hass.loop.time() - self._last_write_monotonic
                        )
                        wait_time = max(
                            0.0,
                            self.min_write_interval - time_since_last,
                        )

                        if wait_time > 0:
                            _LOGGER.info(
                                "⏳ Waiting %.1fs before %s. Queue: %d total",
                                wait_time,
                                write_item.command_name,
                                len(self._pending),
                            )
                            self._changed.clear()
                            try:
                                await asyncio.wait_for(
                                    self._changed.wait(),
                                    timeout=min(
                                        wait_time,
                                        self._write_expiry_remaining(write_item),
                                    ),
                                )
                            except asyncio.TimeoutError:
                                # Re-run the connection and queue checks before
                                # removing the item.  The THOR may have
                                # disconnected during this long rate-limit wait.
                                continue
                            else:
                                # Re-evaluate the head of the queue so a newly
                                # queued control command can run immediately.
                                continue

                    # Keep the item in the queue while rate limiting so a newer
                    # write with the same dedupe key can still replace it.
                    write_item = self._pending.popleft()
                    call_args = list(write_item.args)
                    if write_item.requires_connection:
                        # The current connection can differ from the one that
                        # existed when the UI action was queued.  Rebinding here
                        # prevents commands from being sent to a closed socket.
                        call_args[0] = self.owner.runtime_data["charge_point"]
                    self._active = write_item

                    try:
                        queue_age = (
                            self.owner.hass.loop.time() - write_item.enqueued_at
                        )
                        _LOGGER.info(
                            "✍️ Executing %s [%s] after %.1fs. "
                            "Remaining in queue: %d",
                            write_item.command_name,
                            write_item.command_id,
                            queue_age,
                            len(self._pending),
                        )

                        if write_item.rate_limited:
                            self.owner.pause_polling_until(
                                self.owner.hass.loop.time()
                                + self.poll_pause_after_write
                            )
                            _LOGGER.info(
                                "🛡️ Polling paused BEFORE write "
                                "(Thor FW protection)"
                            )

                        result = await write_item.func(
                            *call_args,
                            **write_item.kwargs,
                        )

                        if (
                            isinstance(result, ChargerWriteResult)
                            and result.status
                            in {
                                ChargerWriteStatus.SKIPPED,
                                ChargerWriteStatus.EXPIRED,
                            }
                        ):
                            self._run_unsent_cleanup(write_item, result)

                        if (
                            write_item.rate_limited
                            and not (
                                isinstance(result, ChargerWriteResult)
                                and result.status
                                in {
                                    ChargerWriteStatus.SKIPPED,
                                    ChargerWriteStatus.EXPIRED,
                                }
                            )
                        ):
                            self._last_write_monotonic = self.owner.hass.loop.time()

                        self._log_write_result(write_item, result)
                        completion_result = (
                            result
                            if isinstance(result, ChargerWriteResult)
                            else ChargerWriteResult.uncertain(
                                "missing_structured_outcome"
                            )
                        )
                        self._resolve_write_result(
                            write_item,
                            completion_result,
                        )

                    except ChargerConnectionUnavailable as err:
                        # The request was definitely not sent.  Put it back at
                        # the front; on the next pass its connection argument is
                        # rebound again.  This differs from an uncertain write,
                        # which must be read back before any retry.
                        if (
                            write_item.policy.reconnect
                            == ChargerWriteReconnectPolicy.DISCARD_WHEN_DISCONNECTED
                        ):
                            self._finish_unsent_write(
                                write_item,
                                ChargerWriteResult.expired(
                                    "discarded_on_disconnect"
                                ),
                            )
                        elif self._write_item_is_expired(write_item):
                            self._finish_unsent_write(
                                write_item,
                                ChargerWriteResult.expired(),
                            )
                        else:
                            self._pending.appendleft(write_item)
                            _LOGGER.info(
                                "↻ Deferring %s until the current connection "
                                "is ready: %s",
                                write_item.command_name,
                                err,
                            )
                        await asyncio.sleep(0)

                    except ChargerRequestOutcomeUncertain as err:
                        if write_item.rate_limited:
                            self._last_write_monotonic = self.owner.hass.loop.time()
                        configuration_key = write_item.configuration_key
                        configuration_generation = write_item.configuration_generation
                        if (
                            configuration_key
                            and configuration_generation is not None
                        ):
                            self.owner.mark_configuration_write(
                                configuration_key,
                                ConfigurationWriteStatus.UNCERTAIN,
                                generation=configuration_generation,
                                result=str(err),
                            )
                            self.owner.schedule_configuration_refresh(delay=0)
                        result = ChargerWriteResult.uncertain(str(err))
                        self._log_write_result(write_item, result)
                        self._resolve_write_result(write_item, result)

                    except asyncio.CancelledError:
                        # The callback may already have handed its request to
                        # OCPP.  Unload therefore resolves the active command
                        # as uncertain, never as safely cancelled or skipped.
                        result = ChargerWriteResult.uncertain(
                            "integration_unloaded_during_execution"
                        )
                        self._log_write_result(write_item, result)
                        self._resolve_write_result(write_item, result)
                        raise

                    except Exception as err:
                        _LOGGER.error("❌ Write command failed: %s", err, exc_info=True)
                        self._resolve_write_result(
                            write_item,
                            ChargerWriteResult.failed("unexpected_error"),
                        )

                    finally:
                        self._active = None

            except asyncio.CancelledError:
                raise
            except Exception:
                # Queue infrastructure must fail closed.  Entries still in
                # the deque are definitely unsent and every waiter receives a
                # terminal result instead of hanging forever.
                _LOGGER.exception("Charger write queue processor failed")
                while self._pending:
                    self._finish_unsent_write(
                        self._pending.popleft(),
                        ChargerWriteResult.skipped(
                            "queue_processor_failed"
                        ),
                    )
            finally:
                self.task = None
                if not self._pending:
                    self.idle.set()

    def cancel(
        self,
        *,
        dedupe_key: str,
        command_name: str | None = None,
        reason: str,
    ) -> int:
        """Cancel matching writes that have definitely not reached OCPP.

        This method intentionally searches only the pending entries.  The active
        item has already crossed the boundary where a request may have reached
        the charger; pretending to cancel it would create a false guarantee for
        automations and could leave Home Assistant out of sync with the THOR.
        """
        retained_items = deque()
        cancelled_items = []
        for item in self._pending:
            matches = item.dedupe_key == dedupe_key and (
                command_name is None
                or item.command_name == command_name
            )
            if matches:
                cancelled_items.append(item)
            else:
                retained_items.append(item)

        if not cancelled_items:
            return 0

        self._pending = retained_items
        for item in cancelled_items:
            self._finish_unsent_write(
                item,
                ChargerWriteResult.skipped(reason),
            )

        # Wake a processor waiting on rate limiting so it re-evaluates its head
        # immediately.  If cancellation emptied the queue, idle is already a
        # truthful state even while the processor task winds down.
        self._changed.set()
        if not self._pending and self._active is None:
            self.idle.set()
        return len(cancelled_items)

    @property
    def has_pending(self) -> bool:
        """Return whether a queued or currently executing write exists."""
        return bool(self._pending) or self._active is not None

    def _log_write_result(self, write_item: ChargerWriteItem, result: Any) -> None:
        """Log the charger outcome instead of merely logging callback return."""
        command_name = write_item.command_name
        command_label = f"{command_name} [{write_item.command_id}]"
        if not isinstance(result, ChargerWriteResult):
            # Legacy callbacks still returning None are intentionally described
            # neutrally.  "Callback finished" must never be mistaken for an
            # acknowledgement from the charger.
            _LOGGER.info(
                "Write callback finished without a structured outcome: %s",
                command_label,
            )
            return

        details = result.reason or result.charger_result or "no details"
        if result.status == ChargerWriteStatus.SUCCESS:
            _LOGGER.info("✅ Write succeeded: %s (%s)", command_label, details)
        elif result.status == ChargerWriteStatus.FAILED:
            _LOGGER.error("❌ Write failed: %s (%s)", command_label, details)
        elif result.status == ChargerWriteStatus.PARTIAL:
            _LOGGER.error(
                "◐ Compound write only partially applied: %s (%s)",
                command_label,
                details,
            )
        elif result.status == ChargerWriteStatus.SKIPPED:
            if result.reason == "replaced_by_newer_intent":
                _LOGGER.info(
                    "↪️ Queued write replaced: %s (%s)",
                    command_label,
                    details,
                )
            elif result.reason and result.reason.startswith("cancelled_by_"):
                _LOGGER.info(
                    "↩️ Queued write cancelled: %s (%s)",
                    command_label,
                    details,
                )
            else:
                _LOGGER.warning("⏭️ Write skipped: %s (%s)", command_label, details)
        elif result.status == ChargerWriteStatus.EXPIRED:
            _LOGGER.warning("⌛ Write expired: %s (%s)", command_label, details)
        else:
            _LOGGER.warning(
                "❔ Write outcome uncertain: %s (%s)",
                command_label,
                details,
            )

    def _resolve_write_result(
        self,
        write_item: ChargerWriteItem,
        result: ChargerWriteResult,
    ) -> ChargerCommandResult:
        """Resolve one completion Future and publish exactly one last result."""
        existing = write_item.terminal_result
        if existing is not None:
            return existing

        completion = ChargerCommandResult.from_write_result(
            command_id=write_item.command_id,
            command_name=write_item.command_name,
            queued_at=write_item.queued_at,
            completed_at=self.owner.now(),
            result=result,
        )
        # Store the terminal result before touching the Future.  Even if a
        # caller cancelled its own wait, every later queue path observes this
        # marker and cannot publish a conflicting second outcome.
        write_item.terminal_result = completion
        future = write_item.completion
        if not future.done():
            future.set_result(completion)
        self.last_result = completion
        try:
            self.owner.publish_write_result(completion)
        except Exception:
            # Entity publication is secondary to resolving the command.  A
            # listener failure must never strand this or later queue waiters.
            _LOGGER.exception(
                "Failed to publish command completion %s",
                completion.command_id,
            )
        return completion

    def _write_item_is_expired(self, write_item: ChargerWriteItem) -> bool:
        """Return whether an unsent queue item has outlived its policy."""
        return self._write_expiry_remaining(write_item) <= 0

    def _write_expiry_remaining(self, write_item: ChargerWriteItem) -> float:
        """Return remaining monotonic lifetime for one unsent command."""
        return max(0.0, write_item.expires_at - self.owner.hass.loop.time())

    def _write_revalidation_failure(self, write_item: ChargerWriteItem) -> str | None:
        """Recheck delayed intent immediately before it may be sent.

        The callback returns ``None`` while the original intent is still valid,
        or a stable diagnostic reason when changed runtime state made it stale.
        Exceptions fail closed so a broken guard can never authorize a write.
        """
        revalidate = write_item.revalidate
        if revalidate is None:
            return None
        try:
            reason = revalidate()
            if reason is None:
                return None
            if not isinstance(reason, str) or not reason:
                raise ValueError(
                    "Write revalidation must return a non-empty reason or None"
                )
            return reason
        except Exception:
            _LOGGER.exception(
                "Write revalidation failed for %s",
                write_item.command_name,
            )
            return "revalidation_error"

    def _finish_unsent_write(
        self,
        write_item: ChargerWriteItem,
        result: ChargerWriteResult,
    ) -> None:
        """Record a terminal outcome for a command never handed to OCPP."""
        configuration_key = write_item.configuration_key
        configuration_generation = write_item.configuration_generation
        if configuration_key and configuration_generation is not None:
            status = (
                ConfigurationWriteStatus.EXPIRED
                if result.status == ChargerWriteStatus.EXPIRED
                else ConfigurationWriteStatus.SKIPPED
            )
            self.owner.mark_configuration_write(
                configuration_key,
                status,
                generation=configuration_generation,
                result=result.reason,
            )
        self._run_unsent_cleanup(write_item, result)
        self._log_write_result(write_item, result)
        self._resolve_write_result(write_item, result)

    def _run_unsent_cleanup(
        self,
        write_item: ChargerWriteItem,
        result: ChargerWriteResult,
    ) -> None:
        """Restore entity-local optimistic state after a command was not sent."""
        on_unsent = write_item.on_unsent
        if on_unsent is not None:
            try:
                on_unsent(result)
            except Exception:
                _LOGGER.exception(
                    "Unsent write cleanup failed for %s",
                    write_item.command_name,
                )

