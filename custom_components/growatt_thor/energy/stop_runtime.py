"""Opt-in charging stop guard using existing, transaction-safe OCPP Stop."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging

from ..ocpp.status import normalize_ocpp_status
from .meter_observations import charging_meter_values
from ..charging.commands import StopChargingCommand
from .stop_guard import (
    AUTO_STOP_MODES, CONF_AUTO_STOP_MODE, STOP_THRESHOLD_W,
    StopGuardTracker, StopObservation,
)
from .observations import parse_at, read_site_observations

_LOGGER = logging.getLogger(__name__)
POLL_SECONDS = 10


class EnergyStopGuard:
    """Observe the active EV session; never alter site-device settings."""

    def __init__(self, hass, coordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.tracker = StopGuardTracker()
        self.stop_command = StopChargingCommand(coordinator)
        self.task: asyncio.Task | None = None

    def mode(self) -> str:
        options = self.coordinator.site_accounting_options
        if options.get("site_accounting_profile") not in ("grid_only", "pv", "pv_battery", "grohome_load_first"):
            return "off"
        mode = options.get(CONF_AUTO_STOP_MODE, "off")
        return mode if mode in AUTO_STOP_MODES else "off"

    def refresh(self) -> None:
        """Apply a saved options change without reloading the integration."""
        if self.mode() == "off":
            if self.task is not None:
                self.task.cancel()
                self.task = None
            self.tracker = StopGuardTracker()
            return
        if self.task is None or self.task.done():
            self.task = self.hass.async_create_background_task(
                self._run(), name="growatt_thor_energy_stop_guard"
            )

    async def async_shutdown(self) -> None:
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    def _observation(self, at: datetime) -> StopObservation:
        coordinator = self.coordinator
        transaction_id = coordinator.transaction_id
        snapshot = coordinator.last_meter_values or {}
        meter = charging_meter_values(snapshot)
        received_at = parse_at(snapshot.get("received_at"))
        sampled_at = parse_at(meter.get("sample_at"))
        gap = coordinator._effective_meter_gap_seconds()
        meter_fresh = (
            received_at is not None and sampled_at is not None
            and 0 <= (at - received_at).total_seconds() <= gap
            and 0 <= (at - sampled_at).total_seconds() <= gap
            and snapshot.get("transaction_id") == transaction_id
            and isinstance(meter.get("power_w"), (int, float))
            and meter["power_w"] > 0
        )
        eligible = (
            self.mode() != "off"
            and coordinator.connected
            and coordinator.transaction_is_active
            and normalize_ocpp_status(coordinator.status) == "charging"
            and transaction_id is not None
            and meter_fresh
        )
        site = read_site_observations(coordinator) if eligible else None
        battery = site.battery.value_at(at) if site and site.battery else None
        grid = site.grid.value_at(at) if site and site.grid else None
        return StopObservation(transaction_id, bool(eligible), battery, grid)

    def _still_eligible(self, expected_transaction_id: int) -> str | None:
        """Recheck live sources before a queued automatic Stop reaches OCPP."""
        value = self._observation(datetime.now(timezone.utc))
        mode = self.mode()
        if value.transaction_id != expected_transaction_id or not value.eligible:
            return "auto_stop_no_longer_eligible"
        battery = (mode in ("battery", "battery_or_grid")
                   and value.battery_discharge_w is not None
                   and value.battery_discharge_w >= STOP_THRESHOLD_W)
        grid = (mode in ("grid", "battery_or_grid")
                and value.grid_import_w is not None
                and value.grid_import_w >= STOP_THRESHOLD_W)
        return None if battery or grid else "auto_stop_condition_cleared"

    async def _run(self) -> None:
        while True:
            at = datetime.now(timezone.utc)
            try:
                reason = self.tracker.evaluate(
                    at, self.mode(), self._observation(at)
                )
                if reason is not None:
                    transaction_id = self.tracker.transaction_id
                    _LOGGER.warning(
                        "Automatic charging stop requested for transaction %s: "
                        "%s power at or above %.0f W for 90 s",
                        transaction_id, reason, STOP_THRESHOLD_W,
                    )
                    # The sustained condition authorizes a request now, but a
                    # queue delay can outlive it. Recheck the live source before send.
                    await self.stop_command.async_request(
                        auto_guard=lambda: self._still_eligible(transaction_id)
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("Automatic charging stop failed; manual stop remains available")
            await asyncio.sleep(POLL_SECONDS)
