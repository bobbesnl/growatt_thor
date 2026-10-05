"""Opt-in charging stop guard using existing, transaction-safe OCPP Stop."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from math import isfinite

from ..ocpp.status import normalize_ocpp_status
from .meter_observations import charging_meter_values
from ..charging.commands import StopChargingCommand
from .stop_guard import (
    AUTO_STOP_MODES, CONF_AUTO_STOP_MODE, CONF_STOP_THRESHOLD, CONF_STOP_HOLD,
    STOP_THRESHOLD_W, STOP_HOLD_SECONDS,
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
        self._configure()

    def _configure(self) -> None:
        options = self.coordinator.site_accounting_options
        def setting(key, default, low, high):
            value = options.get(key, default)
            return float(value) if isinstance(value, (int, float)) and isfinite(value) and low <= value <= high else default
        self.tracker = StopGuardTracker(
            setting(CONF_STOP_THRESHOLD, STOP_THRESHOLD_W, 100, 10000),
            setting(CONF_STOP_HOLD, STOP_HOLD_SECONDS, 30, 1800),
        )

    def mode(self) -> str:
        options = self.coordinator.site_accounting_options
        if options.get("site_accounting_profile") not in ("grid_only", "pv", "pv_battery", "grohome_load_first"):
            return "off"
        mode = options.get(CONF_AUTO_STOP_MODE, "off")
        return mode if mode in AUTO_STOP_MODES else "off"

    def refresh(self) -> None:
        """Apply a saved options change without reloading the integration."""
        self._configure()
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
        solar = site.solar.value_at(at) if site and site.solar else None
        return StopObservation(transaction_id, bool(eligible), battery, grid, solar, meter.get("power_w"))

    def _still_eligible(self, expected_transaction_id: int) -> str | None:
        """Recheck live sources before a queued automatic Stop reaches OCPP."""
        at = datetime.now(timezone.utc)
        value = self._observation(at)
        mode = self.mode()
        if (value.transaction_id != expected_transaction_id or not value.eligible
                or self.tracker.transaction_id != expected_transaction_id
                or self.tracker.above_since is None):
            return "auto_stop_no_longer_eligible"
        if self.tracker.above_since is not None and (
            at - self.tracker.above_since
        ).total_seconds() < self.tracker.required_hold(value):
            return "auto_stop_pv_grace"
        battery = (mode in ("battery", "battery_or_grid")
                   and value.battery_discharge_w is not None
                   and value.battery_discharge_w >= self.tracker.threshold_w)
        grid = (mode in ("grid", "battery_or_grid")
                and value.grid_import_w is not None
                and value.grid_import_w >= self.tracker.threshold_w)
        return None if battery or grid else "auto_stop_condition_cleared"

    async def _run(self) -> None:
        while True:
            at = datetime.now(timezone.utc)
            try:
                observation = self._observation(at)
                reason = self.tracker.evaluate(at, self.mode(), observation)
                if reason is not None:
                    transaction_id = self.tracker.transaction_id
                    _LOGGER.warning(
                        "Automatic charging stop requested for transaction %s: "
                        "%s power at or above %.0f W for %.0f s",
                        transaction_id, reason, self.tracker.threshold_w, self.tracker.required_hold(observation),
                    )
                    # The sustained condition authorizes a request now, but a
                    # queue delay can outlive it. Recheck the live source before send.
                    await self.stop_command.async_request(
                        auto_guard=lambda: self._still_eligible(transaction_id),
                        stop_reason=f"energy_guard_{reason}",
                    )
                    # Store only an accepted protection Stop, not an expired
                    # queued intention. The event keeps its reason in history.
                    self.coordinator.last_energy_stop = {
                        "reason": reason, "at": at.isoformat(), "transaction_id": transaction_id,
                        "threshold_w": self.tracker.threshold_w,
                        "hold_seconds": self.tracker.required_hold(observation),
                        "observed_w": (observation.battery_discharge_w if reason == "battery" else observation.grid_import_w),
                    }
                    self.coordinator._schedule_storage_save()
                    self.coordinator.async_set_updated_data(True)
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("Automatic charging stop failed; manual stop remains available")
            await asyncio.sleep(POLL_SECONDS)
