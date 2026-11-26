"""Inbound OCPP observations applied to one charger's coordinator state.

The OCPP adapter calls these through the coordinator. State stays on the
coordinator, and every clock read, storage save and update notification goes
through it, so the coordinator remains the single owner of what HA observes.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from ..charging.faults import fault_from_data_transfer, fault_from_status_notification
from ..coerce import enum_value
from ..configuration.values import (
    COORDINATOR_CONFIGURATION_PROJECTIONS,
    merge_configuration_values,
    normalize_unknown_configuration_keys,
    parse_auto_charge_time,
)
from ..energy.site_inputs import site_inputs
from ..ocpp.core.diagnostics import create_ocpp_snapshot
from ..ocpp.core.meter_samples import (
    DEFAULT_MEASURAND,
    MeterValue,
    charging_power_curve_point,
    meter_time_zone,
    parse_meter_values,
)
from ..ocpp.core.status import ENERGY_SESSION_STATUSES, LIVE_POWER_STATUSES, normalize_ocpp_status
from ..ocpp.growatt.external_meter import parse_external_meter_data
from ..sessions.events import append_session_event, session_event
from ..sessions.series import SESSION_CURVE_POINT_LIMIT, downsample_curve
from ..timestamps import installation_time_zone
from ..timestamps import parse_utc as parse_at
from .keys import UPDATE_SESSION_EVENTS_IN_CSV

if TYPE_CHECKING:
    from ..coordinator import GrowattCoordinator

_LOGGER = logging.getLogger(__name__)

# OCPP statuses in which the charger delivers energy. In every other status
# the last MeterValues sample is stale, so live power and current go to 0.
MIN_METER_GAP_SECONDS = 30.0
METER_GAP_INTERVAL_MULTIPLIER = 3
DEFAULT_METER_GAP_SECONDS = 180.0


LIVE_SAMPLE_PROJECTIONS = {
    DEFAULT_MEASURAND: ("energy", False),
    "Power.Active.Import": ("phase_power", True),
    "Current.Import": ("currents", True),
    "Voltage": ("voltages", True),
    "Temperature": ("temperature", False),
}


class OcppIngest:
    """Apply BootNotification, StatusNotification, MeterValues, configuration and
    Growatt DataTransfer observations."""

    def __init__(self, coordinator: GrowattCoordinator) -> None:
        self.coordinator = coordinator

    def reset_live_power(self) -> bool:
        """Zero live power and current values that are no longer current.

        The THOR sends MeterValues only while it charges.  When charging ends
        with the cable still connected (SuspendedEV) no StopTransaction
        follows, so without this reset the last sample stays visible until
        the cable is unplugged.  Voltages are kept: the charger still sees
        mains voltage.
        """
        zero_phases = {"L1": 0, "L2": 0, "L3": 0}
        if (
            self.coordinator.power == 0
            and self.coordinator.phase_power == zero_phases
            and self.coordinator.currents == zero_phases
        ):
            return False

        self.coordinator.power = 0
        self.coordinator.phase_power = dict(zero_phases)
        self.coordinator.currents = dict(zero_phases)
        return True

    def observe_status(self, status: object) -> None:
        """Set charger status and notify sensors."""
        value = enum_value(status, stringify_fallback=True)

        if self.coordinator.status != value:
            self.coordinator.status = value
            _LOGGER.debug("Status changed to: %s", value)

        normalized = normalize_ocpp_status(value)
        if (
            normalized is not None
            and normalized not in LIVE_POWER_STATUSES
            and self.reset_live_power()
        ):
            _LOGGER.info("Status %s: live power reset to 0 W", value)

        self.coordinator.async_set_updated_data(True)

    def observe_boot_notification(self, payload: dict[str, Any]) -> None:
        """Retain the latest BootNotification request."""
        self.coordinator.boot_notification = create_ocpp_snapshot(self.coordinator.now(), payload)
        self.coordinator.async_set_updated_data(True)

    def observe_status_notification(
        self,
        connector_id: int,
        status: str,
        error_code: str | None = None,
        **payload: Any,
    ) -> None:
        """Retain the latest StatusNotification request and update its state."""
        request = {
            "connector_id": connector_id,
            "status": status,
            "error_code": error_code,
            **payload,
        }
        previous_status = normalize_ocpp_status(self.coordinator.status)
        self.coordinator.last_status_notification = create_ocpp_snapshot(
            self.coordinator.now(), request
        )
        received_at = self.coordinator.last_status_notification["received_at"]
        normalized_status = normalize_ocpp_status(status)
        target = self.coordinator.active_transaction or self.coordinator.last_completed_transaction
        target_connector = (
            target.get("start", {}).get("request", {}).get("connector_id")
            if isinstance(target, dict)
            else None
        )
        session_connector = (
            connector_id is not None
            and str(connector_id) != "0"
            and (target_connector is None or str(target_connector) == str(connector_id))
        )
        if normalized_status in ENERGY_SESSION_STATUSES:
            self.coordinator.sessions.restored_active_session = False
        elif normalized_status == "available":
            self.coordinator.sessions.discard_unconfirmed_restored_session()
        if (
            normalized_status == "preparing"
            and session_connector
            and previous_status in (None, "available", "idle")
        ):
            self.coordinator.sessions.pending_plugged_event = session_event(
                "plugged_in", received_at, "ocpp", "derived"
            )
        elif normalized_status == "available" and session_connector:
            unplugged = session_event("unplugged", received_at, "ocpp", "derived")
            target = (
                self.coordinator.active_transaction or self.coordinator.last_completed_transaction
            )
            if isinstance(target, dict):
                events = target.setdefault("events", [])
                event_added = append_session_event(events, unplugged, unique_type=True)
                session_id = target.get("session_id")
                update_fn = self.coordinator.runtime_data.get(UPDATE_SESSION_EVENTS_IN_CSV)
                if event_added and session_id and update_fn:
                    self.coordinator.hass.async_create_task(update_fn(session_id, list(events)))
            self.coordinator.sessions.pending_plugged_event = None
        # Connector 0 describes the whole station, not the active EV session.
        # Use receipt time: this is when we observed the pause, not an inferred
        # final power sample or the unknown time at which the car became full.
        transaction = self.coordinator.active_transaction
        tracker = self.coordinator.sessions.event_tracker
        if transaction and tracker is not None and session_connector:
            if tracker.observe_suspension(received_at, normalized_status):
                self.coordinator.schedule_storage_save()
        new_fault = None
        if normalize_ocpp_status(status) == "faulted":
            self.coordinator.last_charger_fault = fault_from_status_notification(
                self.coordinator.now(),
                connector_id,
                error_code,
                payload,
            )
            self.coordinator.schedule_fault_storage_save()
            # A repeated Faulted report is the same fault, not a new event.
            if previous_status != "faulted":
                new_fault = self.coordinator.last_charger_fault
        info = payload.get("info")
        self.coordinator.external_meter.observe_status(connector_id, error_code, info)
        self.observe_status(status)
        if new_fault is not None:
            self.coordinator.events.fault(new_fault)

    def observe_fault_message(
        self,
        vendor_id: object,
        data: str,
    ) -> None:
        """Retain and merge a Growatt DataTransfer/faultmessage event."""
        self.coordinator.last_charger_fault = fault_from_data_transfer(
            self.coordinator.now(),
            vendor_id,
            data,
            self.coordinator.last_charger_fault,
        )
        self.coordinator.schedule_fault_storage_save()
        self.coordinator.async_set_updated_data(True)

    def observe_meter_values(
        self,
        meter_values: list[dict[str, Any]],
        *,
        connector_id: int | None = None,
        transaction_id: int | str | None = None,
    ) -> None:
        """Retain all MeterValues samples and update known live sensors."""
        if not self._accept_meter_transaction(transaction_id):
            return
        parsed_values = parse_meter_values(
            meter_values,
            time_zone=meter_time_zone(
                self.coordinator.configuration_values,
                installation_time_zone(self.coordinator.hass, None, preserve_empty=True),
            ),
        )
        self.coordinator.last_meter_values = {
            "received_at": self.coordinator.now(),
            "connector_id": connector_id,
            "transaction_id": transaction_id,
            "meter_values": [entry.as_dict() for entry in parsed_values],
        }
        received_at = parse_at(self.coordinator.last_meter_values["received_at"])
        self._observe_site_accounting(parsed_values, received_at, transaction_id)
        effective_transaction_id = self._observe_effective_charging(parsed_values, transaction_id)
        self.coordinator.sessions.observe_context()
        for entry in parsed_values:
            if self.coordinator.sessions.observe_meter(
                entry, self.coordinator.last_meter_values["received_at"]
            ):
                self.coordinator.schedule_storage_save()

        live_power = self._live_power_follows_samples()
        updated = False
        ignored_live_samples = False
        for entry in parsed_values:
            entry_updated, entry_ignored = self._apply_live_samples(entry, live_power=live_power)
            updated = entry_updated or updated
            ignored_live_samples = entry_ignored or ignored_live_samples
            self._append_power_curve(entry, effective_transaction_id)

        if self.coordinator.phase_power:
            total = sum(self.coordinator.phase_power.values())
            if self.coordinator.power != total:
                self.coordinator.power = total
                updated = True

        if ignored_live_samples:
            _LOGGER.debug(
                "Ignoring live power and current from MeterValues while status is %s",
                self.coordinator.status,
            )
        _LOGGER.debug(
            "Retained %d MeterValues entries%s",
            len(parsed_values),
            " and updated live sensors" if updated else "",
        )
        self.coordinator.async_set_updated_data(True)

    def _accept_meter_transaction(self, transaction_id: int | str | None) -> bool:
        if transaction_id is not None:
            active_id = self.coordinator.transaction_id
            if active_id is None:
                # Reconnect recovery requires a charging observation; late
                # telemetry alone cannot resurrect an ended transaction.
                if normalize_ocpp_status(self.coordinator.status) not in {
                    "charging",
                    "suspended_ev",
                    "suspended_evse",
                }:
                    return False
                self.coordinator.transaction_id = transaction_id
                self.coordinator.schedule_storage_save()
            elif str(transaction_id) != str(active_id):
                _LOGGER.info("Ignoring MeterValues for inactive transaction %s", transaction_id)
                return False
        return True

    def _observe_site_accounting(
        self,
        parsed_values: Sequence[MeterValue],
        received_at: datetime | None,
        transaction_id: int | str | None,
    ) -> None:
        if (
            self.coordinator.site_accounting is not None
            and str(transaction_id or self.coordinator.transaction_id)
            == self.coordinator.site_accounting.transaction_id
        ):
            accounting_updated = False
            for entry in parsed_values:
                at = parse_at(entry.timestamp)
                if at is None or received_at is None or at > received_at:
                    continue
                power_point = charging_power_curve_point(entry)
                if power_point is not None:
                    accounting_updated = (
                        self.coordinator.site_accounting.observe_power_fallback(power_point[1], at)
                        or accounting_updated
                    )
                for sample in entry.samples:
                    if (
                        sample.measurand != DEFAULT_MEASURAND
                        or sample.numeric_value is None
                        or sample.phase is not None
                    ):
                        continue
                    # A long telemetry gap cannot be priced/classified from
                    # just the current site snapshot (including after upgrade).
                    previous_at = self.coordinator.site_accounting.last_meter_at
                    max_gap = self.effective_meter_gap_seconds
                    current_interval = (
                        previous_at is not None
                        and 0 <= (at - previous_at).total_seconds() <= max_gap
                        and 0 <= (received_at - at).total_seconds() <= max_gap
                    )
                    accounting_updated = (
                        self.coordinator.site_accounting.observe(
                            meter_wh=sample.numeric_value,
                            at=at,
                            site_id=self.coordinator.source_instance_id or "site",
                            charger_id=self.coordinator.charge_point_id or "charger",
                            inputs=site_inputs(self.coordinator, at, received_at=received_at)
                            if current_interval
                            else None,
                            context=sample.context,
                            unit=sample.unit,
                        )
                        or accounting_updated
                    )
            if accounting_updated:
                self.coordinator.hass.async_create_task(self.coordinator.async_save_storage())

    def _observe_effective_charging(
        self, parsed_values: Sequence[MeterValue], transaction_id: int | str | None
    ) -> int | str | None:
        effective_transaction_id = (
            transaction_id if transaction_id is not None else self.coordinator.transaction_id
        )
        if effective_transaction_id is not None:
            previous_transaction_id = self.coordinator.effective_charging.transaction_id
            self.coordinator.effective_charging.start(effective_transaction_id)
            effective_updated = (
                previous_transaction_id != self.coordinator.effective_charging.transaction_id
            )
            max_gap_seconds = self.effective_meter_gap_seconds
            for entry in parsed_values:
                effective_updated = (
                    self.coordinator.effective_charging.observe(
                        entry,
                        max_gap_seconds=max_gap_seconds,
                    )
                    or effective_updated
                )
            if effective_updated:
                self.coordinator.schedule_storage_save()

        return effective_transaction_id

    def _apply_live_samples(self, entry: MeterValue, *, live_power: bool) -> tuple[bool, bool]:
        updated = False
        ignored_live_samples = False
        for sample in entry.samples:
            value = sample.numeric_value
            if value is None:
                _LOGGER.warning(
                    "Failed to parse MeterValues sample value %r for %s",
                    sample.raw_value,
                    sample.measurand,
                )
                continue

            if sample.measurand in ("Power.Active.Import", "Current.Import") and not live_power:
                # Retained above in last_meter_values for diagnostics,
                # but not shown as live: the charger reports that it is
                # not delivering energy.
                ignored_live_samples = True
                continue

            projection = LIVE_SAMPLE_PROJECTIONS.get(sample.measurand)
            if projection is None:
                continue
            attribute, phased = projection
            if sample.measurand == DEFAULT_MEASURAND and sample.context == "Transaction.Begin":
                _LOGGER.debug("Skipping transaction-begin energy sample: %.3f Wh", value)
                continue
            if phased:
                observations = getattr(self.coordinator, attribute)
                phase = sample.phase or "L1"
                if observations.get(phase) != value:
                    observations[phase] = value
                    updated = True
            elif getattr(self.coordinator, attribute) != value:
                setattr(self.coordinator, attribute, value)
                updated = True

        return updated, ignored_live_samples

    def _append_power_curve(
        self, entry: MeterValue, effective_transaction_id: int | str | None
    ) -> None:
        if effective_transaction_id is not None:
            point = charging_power_curve_point(entry)
            if point is not None and (
                not self.coordinator.sessions.active_power_curve
                or self.coordinator.sessions.active_power_curve[-1][0] != point[0]
            ):
                self.coordinator.sessions.active_power_curve.append(point)
                if (
                    len(self.coordinator.sessions.active_power_curve)
                    > SESSION_CURVE_POINT_LIMIT * 2
                ):
                    self.coordinator.sessions.active_power_curve = downsample_curve(
                        self.coordinator.sessions.active_power_curve,
                        limit=SESSION_CURVE_POINT_LIMIT,
                        event_times=(
                            event.get("at")
                            for event in (
                                self.coordinator.sessions.event_tracker.events
                                if self.coordinator.sessions.event_tracker is not None
                                else ()
                            )
                        ),
                    )
                if self.coordinator.sessions.event_tracker is not None:
                    self.coordinator.sessions.event_tracker.observe_power(point[0], point[1])
                self.coordinator.schedule_storage_save()

    def _live_power_follows_samples(self) -> bool:
        """Return whether MeterValues may update live power and current.

        Live power and current follow samples only while the charger reports
        Charging, or while no status is known yet.  In every other status the
        charger is not delivering energy, so a sample that arrives late (for
        example a MeterValues report after SuspendedEV) must not bring the
        last charging power back.  When the vehicle draws again the THOR
        reports Charging first, so valid measurements apply again at once.
        """
        normalized = normalize_ocpp_status(self.coordinator.status)
        return normalized is None or normalized in LIVE_POWER_STATUSES

    @property
    def effective_meter_gap_seconds(self) -> float:
        """Bound counted intervals using the charger-reported sample period."""
        for key in ("G_MeterValueInterval", "MeterValueSampleInterval"):
            value = self.coordinator.configuration_values.get(key)
            if value is None:
                continue
            try:
                interval = float(cast(Any, value.parsed_value))
            except (TypeError, ValueError):
                continue
            if interval > 0:
                return max(MIN_METER_GAP_SECONDS, interval * METER_GAP_INTERVAL_MULTIPLIER)
        return DEFAULT_METER_GAP_SECONDS

    def observe_configuration(
        self, configuration: Sequence[object], unknown_keys: Iterable[object] = ()
    ) -> None:
        """Validate configuration responses and safely reject malformed values."""
        self.coordinator.configuration_values, updated = merge_configuration_values(
            self.coordinator.configuration_values,
            (item for item in configuration if isinstance(item, dict)),
        )

        normalized_unknown_keys = normalize_unknown_configuration_keys(unknown_keys)
        if self.coordinator.unknown_configuration_keys != normalized_unknown_keys:
            self.coordinator.unknown_configuration_keys = normalized_unknown_keys
            updated = True

        self.coordinator.sessions.observe_context()

        reported_values = {
            str(item["key"]): (None if item.get("value") is None else str(item.get("value")))
            for item in configuration
            if isinstance(item, dict) and item.get("key")
        }
        if self.coordinator.configuration_write_tracker.confirm_readback(reported_values):
            updated = True

        if self.coordinator.pv_draft.initialize(self.coordinator.configuration_values):
            updated = True

        for item in configuration:
            if not isinstance(item, dict):
                continue
            key: Any = item.get("key")
            raw = item.get("value")

            try:
                if key == "G_AutoChargeTime":
                    updated = self._apply_auto_charge_time(raw) or updated
                    continue
                projection = COORDINATOR_CONFIGURATION_PROJECTIONS.get(key)
                if projection is None:
                    continue
                parser, attribute = projection
                value = parser(raw, self.coordinator.configuration_values.get(key))
                if value is None and key in {
                    "G_MaxCurrent",
                    "G_ExternalLimitPower",
                    "G_TimeSharingPrice",
                }:
                    if key == "G_TimeSharingPrice":
                        _LOGGER.warning(
                            "Could not parse G_TimeSharingPrice from raw value: %s", raw
                        )
                    continue
                if getattr(self.coordinator, attribute) != value:
                    setattr(self.coordinator, attribute, value)
                    _LOGGER.debug("Config: %s = %s", attribute, value)
                    updated = True

            except (ValueError, TypeError) as exc:
                _LOGGER.warning("Failed to parse config key=%s value=%s: %s", key, raw, exc)
                continue
            except Exception as exc:
                # A failed projection must not discard the remaining configuration keys.
                _LOGGER.error(
                    "Unexpected error processing config key=%s: %s",
                    key,
                    exc,
                    exc_info=True,
                )
                continue

        if updated:
            self.coordinator.async_set_updated_data(True)

    def _apply_auto_charge_time(self, raw: object) -> bool:
        try:
            schedule = parse_auto_charge_time(cast(Any, raw))
        except ValueError as exc:
            _LOGGER.warning("Failed to parse G_AutoChargeTime '%s': %s", raw, exc)
            return False
        if schedule is None:
            return False
        updated = False
        for attribute, value in zip(
            ("auto_charge_start_time", "auto_charge_stop_time"), schedule, strict=True
        ):
            if getattr(self.coordinator, attribute) != value:
                setattr(self.coordinator, attribute, value)
                setattr(self.coordinator, attribute + "_pending", value)
                _LOGGER.debug("Config: %s = %s", attribute, value)
                updated = True
        return updated

    def observe_external_meter_timeout(self) -> None:
        """Record one missed external-meter response and refresh HA state."""
        self.coordinator.external_meter.consecutive_timeouts += 1
        self.coordinator.async_set_updated_data(True)

    def observe_external_meter_values(self, data_str: str) -> bool:
        """Process external meter values from get_external_meterval DataTransfer."""
        try:
            snapshot = parse_external_meter_data(data_str)
            self.coordinator.external_meter.apply_snapshot(snapshot, self.coordinator.now())
            self.coordinator.sessions.observe_context()
            _LOGGER.debug(
                "External meter snapshot: used=%s wring=%s power=%s voltages=%s currents=%s",
                snapshot.used,
                snapshot.wring,
                snapshot.power,
                snapshot.voltages,
                snapshot.currents,
            )
            self.coordinator.async_set_updated_data(True)
            return True

        except (ValueError, TypeError, KeyError) as exc:
            _LOGGER.warning("Failed to process external meter data '%s': %s", data_str, exc)
            return False
