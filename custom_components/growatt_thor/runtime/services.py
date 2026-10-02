"""Coordinate integration services without depending on Home Assistant APIs.

Service handlers may be invoked concurrently by dashboards and automations.
This module owns the timing rules for those calls so that the Home Assistant
registration layer only has to translate inputs and failures.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import TypeVar


ResultT = TypeVar("ResultT")


class ChargerServiceUnavailable(RuntimeError):
    """The loaded runtime has no usable charger connection."""


class ManualRefreshFailed(RuntimeError):
    """One named read in the manual refresh sequence did not complete."""

    def __init__(self, step: str) -> None:
        super().__init__(step)
        self.step = step


class IntegrationServiceOperations:
    """Share refreshes and same-target exports between concurrent callers."""

    def __init__(
        self,
        create_task: Callable[[Awaitable], asyncio.Task],
    ) -> None:
        self._create_task = create_task
        self._refresh_task: asyncio.Task | None = None
        self._export_tasks: dict[str, asyncio.Task] = {}

    async def async_refresh(self, runtime_data: Mapping[str, object]) -> None:
        """Join one in-flight refresh, or start exactly one new sequence."""
        task = self._refresh_task
        if task is None or task.done():
            charge_point = runtime_data.get("charge_point")
            coordinator = runtime_data.get("coordinator")
            if (
                charge_point is None
                or coordinator is None
                or not getattr(coordinator, "connected", False)
            ):
                raise ChargerServiceUnavailable

            task = self._create_task(self._run_refresh(charge_point))
            self._refresh_task = task
            task.add_done_callback(self._release_refresh_task)

        # One cancelled HA service caller must not cancel the shared physical
        # sequence while another caller is still waiting for the same result.
        await asyncio.shield(task)

    async def _run_refresh(self, charge_point) -> None:
        """Run each optional read and stop as soon as a write takes priority."""
        steps = (
            ("status", charge_point.trigger_status),
            ("external_meter", charge_point.trigger_external_meterval),
            ("configuration", charge_point.trigger_get_configuration),
        )
        for step, operation in steps:
            try:
                completed = await operation(skip_if_writes_pending=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise ManualRefreshFailed(step) from exc
            if not completed:
                # The request gate returns False when a user write appeared
                # before this diagnostic read could acquire the OCPP lock. It
                # is intentionally not retried here: the write gets immediate
                # priority and the service reports that its refresh was not
                # complete instead of pretending success.
                raise ManualRefreshFailed(step)

    def _release_refresh_task(self, completed: asyncio.Task) -> None:
        """Forget only the task that still owns the single-flight slot."""
        if self._refresh_task is completed:
            self._refresh_task = None
        _consume_background_exception(completed)

    async def async_export(
        self,
        target: str,
        export: Callable[[], Awaitable[ResultT]],
    ) -> ResultT:
        """Join an export already writing the same normalized target path."""
        task = self._export_tasks.get(target)
        if task is None or task.done():
            task = self._create_task(export())
            self._export_tasks[target] = task
            task.add_done_callback(
                lambda completed, target=target: self._release_export_task(
                    target,
                    completed,
                )
            )
        return await asyncio.shield(task)

    def _release_export_task(
        self,
        target: str,
        completed: asyncio.Task,
    ) -> None:
        """Release one path without touching a newer export for that path."""
        if self._export_tasks.get(target) is completed:
            self._export_tasks.pop(target, None)
        _consume_background_exception(completed)


def _consume_background_exception(task: asyncio.Task) -> None:
    """Avoid an unobserved exception if every shielded caller was cancelled."""
    if not task.cancelled():
        task.exception()
