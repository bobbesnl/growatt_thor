# 0001. Route every outbound charger write through one queue per charger

Status: Accepted

## Context

Many parts of the integration want to change the charger: entities, HA services,
charging targets, PV Linkage Apply and the automatic stop guard. HA automations
can trigger them in quick succession and in unusual orders. The THOR firmware
does not cope well with overlapping requests: configuration writes need spacing,
and polling right before a write can disturb it. A reconnect can also replace the
WebSocket while work is waiting.

## Decision

Each config entry creates one `ChargerWriteQueue`. It is the only component that
sends charger writes. Callers enqueue a callback with a policy (lifetime and
reconnect behavior), an optional dedupe key and an optional revalidation check.
The queue orders priority work first, spaces rate-limited writes, pauses polling
before them, rebinds the current charge point and revalidates the intent
immediately before execution. Every enqueued command gets exactly one terminal
result.

## Consequences

- Ordering, spacing, replacement of unsent intents and shutdown are handled in
  one place and tested there.
- Callers never hold a charge point reference across a wait; they read the
  current connection when they act.
- New write paths must be expressed as queue callbacks. Calling
  `GrowattChargePoint` write methods directly is a defect.
- Enforced by the [invariants](../invariants.md#commands-and-transactions), the
  queue tests and `control_write_contracts.json`. Background:
  [automation resilience](../automation-resilience.md#3-expire-and-revalidate-delayed-commands).
