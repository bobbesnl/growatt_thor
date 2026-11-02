# 0003. Use the wallbox's native functions for charging targets

Status: Accepted

## Context

Users want to charge a given energy amount, for a given duration or (experimentally)
up to a budget, now or at a later time. HA could implement this itself with timers
and energy counters, but such a controller would fail while HA restarts, would
compete with the wallbox's own logic and would duplicate behavior the firmware
already offers.

## Decision

One-time energy, duration and budget targets are sent to the wallbox, which
enforces them. A one-time start at a set time uses a wallbox reservation. Only the
daily repeat schedule is stored and executed by HA. Native one-shot targets,
persistent charging windows, reservations and app/cloud schedules stay distinct,
even if their UI labels look similar. Target requests are persisted; unresolved
requests block ordinary starts until they are reconciled and are not retried
automatically.

## Consequences

- Charging targets keep working while HA is unavailable, once accepted by the
  wallbox.
- Behavior depends on firmware. Energy and duration enforcement is verified only
  on the documented THOR 22AS firmware; budget stopping remains experimental.
- New target features need capture evidence before writes are implemented.
- Enforced by the [invariants](../invariants.md#automatic-stop-and-targets) and
  the target service tests. Background:
  [backlog design decisions](../backlog.md#design-decisions) and
  [charging-target evidence](../../reverse_engineering/charging_targets.md).
