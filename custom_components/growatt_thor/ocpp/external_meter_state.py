"""The external meter's last observations and communication state."""

from dataclasses import dataclass, field

from ..coerce import enum_value
from ..const import DEFAULT_POLL_INTERVAL
from .external_meter import (
    ExternalMeterSnapshot,
    external_meter_health,
    status_clears_external_meter_fault,
    status_reports_external_meter_fault,
)


@dataclass(slots=True)
class ExternalMeterState:
    power: float | None = None
    voltages: dict[str, float] = field(default_factory=dict)
    currents: dict[str, float] = field(default_factory=dict)
    used: int | None = None
    wring: int | None = None
    last_updated_at: str | None = None
    poll_interval: int = DEFAULT_POLL_INTERVAL
    faulted: bool = False
    fault_connector_id: int | str | None = None
    fault_error_code: str | None = None
    fault_info: object = None
    consecutive_timeouts: int = 0

    @property
    def health(self) -> str:
        return external_meter_health(
            explicit_fault=self.faulted,
            consecutive_timeouts=self.consecutive_timeouts,
            has_snapshot=self.last_updated_at is not None,
        )

    def apply_snapshot(self, snapshot: ExternalMeterSnapshot, at: str) -> None:
        self.consecutive_timeouts = 0
        for name in ("used", "wring", "voltages", "currents", "power"):
            value = getattr(snapshot, name)
            if getattr(self, name) != value:
                setattr(self, name, value)
        self.last_updated_at = at

    def observe_status(
        self, connector_id: int | str | None, error_code: object, info: object
    ) -> None:
        if status_reports_external_meter_fault(error_code, info):
            self.faulted = True
            self.fault_connector_id = connector_id
            self.fault_error_code = enum_value(error_code)
            self.fault_info = info
        elif (
            self.faulted
            and status_clears_external_meter_fault(error_code)
            and connector_id == self.fault_connector_id
        ):
            self.faulted = False
            self.fault_connector_id = None
            self.fault_error_code = None
            self.fault_info = None
