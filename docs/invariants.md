# Safety and compatibility invariants

[Documentation](../README.md#documentation) · [Architecture](architecture.md) · [Decision records](adr/README.md)

These rules protect users, chargers and existing installations. Read them before
changing the write queue, Start/Stop, charging targets, configuration writes or
OCPP handlers, together with [automation resilience](automation-resilience.md).
A change that would break one of them is a behavior change: discuss it separately
instead of folding it into a refactoring. The reasons behind the most important
rules are recorded as [decision records](adr/README.md).

## Commands and transactions

- The write queue is the only owner of outbound charger writes for each charger
  ([ADR 0001](adr/0001-single-charger-write-owner.md)). Entities, services, the
  target runtime and the stop guard enqueue work; they never call the charge
  point directly.
- An accepted command does not prove that a transaction started, stopped or
  moved energy. Queue status, charger observations and energy flow remain
  distinct.
- A command whose outcome is uncertain is never replayed automatically
  ([ADR 0002](adr/0002-no-automatic-replay-of-uncertain-commands.md)).
- Connection-bound commands are rebound to the current socket immediately before
  execution and revalidated at that point.
- Stop cancels an unsent Start before considering a physical Stop. A Stop is
  tied to the observed transaction; a later transaction invalidates it.
- Start and Stop buttons call `GrowattOcppCharger`, the `ChargerControl`
  implementation, which delegates to `StartChargingCommand` and
  `StopChargingCommand` in `charging/commands.py`. These commands own
  revalidation, queue submission and command-state reporting. Delayed status
  triggers resolve the current connection after the two-second delay.
- Shutdown closes queue admission and cancels active work first, then resolves
  pending entries as unsent. Active work stays uncertain because it may already
  have reached OCPP. Every handle receives exactly one terminal result.

## Automatic stop and targets

- The automatic guard reads shared observations and calls the Stop command
  through `ChargerControl`. It takes one charger snapshot per evaluation, so
  connection, status, transaction and meter reading come from the same moment.
  It imports neither dashboard projection nor accounting runtime, never requires
  a registered button and cannot restart charging.
- Target services keep their public names and the charging-target storage key.
  Wallbox-native energy/time limits and HA-owned repeat scheduling stay separate
  ([ADR 0003](adr/0003-native-charging-targets.md)).

## Observations

- Unit and sign normalization is shared. Automatic controls require recent
  source reports; display and accounting accept available, unchanged HA sensor
  states. THOR meter freshness is checked in both cases.
- Missing and unavailable values are not zero.

## View contract

- At most 20 recent rows, 24 events and 96 curve points per session, with a
  12 KiB target. Historical detail is loaded on demand. Pagination covers the
  recent rows, not the full archive.

## OCPP handlers and logging

- Inbound OCPP actions share `guarded_ocpp_handler`. Each action keeps its
  fallback reply; superseded `DataTransfer` sockets get a separate rejected reply.
- `StartTransaction` rechecks socket ownership after allocating its transaction
  ID, before it changes coordinator state.
- Handler exceptions are logged with tracebacks, except for authorization and
  transaction actions. Those log without payload so RFID identifiers do not reach
  the log ([ADR 0005](adr/0005-rfid-safe-logging.md)).
- Configuration groups apply operational keys before the informational request.
  Logged configuration values are redacted.
- The OCPP message log in diagnostics stores payloads only after redaction:
  identifiers by field name, configuration values by registry sensitivity and
  Growatt DataTransfer data except `get_external_meterval`. It stays in memory
  and bounded, and records only the socket that owns the runtime.
- Socket closes share one bounded close helper; ownership release stays with the
  connection owner.

## Error boundaries

Broad exception handlers document the boundary they protect: OCPP fallback
replies, terminal command results, independent polling cycles, durable session
delivery or resource cleanup.

- Keep specific transport and uncertain-outcome handling ahead of those fallbacks.
- `BaseException` handlers only perform cleanup or restore retryable state, then
  re-raise. They do not convert cancellation into a normal result.
- Keep payload-free logging at RFID-sensitive boundaries.

## Stable identities

Entity unique IDs and entity-ID schemes, service names, config-entry keys,
storage keys, persisted strings and translation keys stay byte-identical. The
contract fixtures in [`tests/fixtures`](../tests/fixtures/README.md) check these
boundaries. See the [refactoring contracts](CONTRIBUTING.md#refactoring-contracts).

## Configuration write behavior per entity

`ConfigurationWriter` in `configuration/writer.py` owns the order of the shared
steps; each entity's `WritePolicy` supplies encoding, block reasons, optimistic
and accepted state, rollback and the exception boundary. Mode-aware controls
are declared from descriptions and hold a `ConfigurationControl` from
`configuration/controls.py` for the pending-state projection and the shared
`ConfigurationControlWritePolicy`. All writes run inside write-queue callbacks.
The differences below are intentional:

| Entity | State and rollback behavior |
| --- | --- |
| Max current | Optimistic current. Restore the last reported value only for the owning generation on rejection, unsent completion or unexpected failure; keep the requested value after uncertainty. Recheck model limits before sending. |
| Load balancing limit | Same rollback protection. Publish the acknowledged configuration and schedule readback before updating the numeric observation. |
| Electricity price | Optimistic price with generation-safe rollback. Keep the exact requested numeric value while encoding the two-decimal full-day tariff on the wire. |
| Load balancing switch | Pending state comes from write tracking. Acknowledge and schedule readback before updating the enabled observation. Unexpected failures propagate to the queue. |
| LCD switch | Pending write tracking stays visible. Update the LCD observation before the reported configuration, notify on rejection, and keep the transport-only exception boundary. |
| Working mode | An entity intent token protects selections across different configuration keys. It has its own readback waiter and clears only the matching selection; uncertainty schedules that waiter's immediate readback. |
| Auto Charge times | Two fields share one debounce and one queued snapshot. Restore pending fields only for an unsent owning generation; rejection and unexpected execution failure do not roll back. The HA calls return before the deferred command completes. |

The three optimistic Number controls share `OptimisticNumberPolicy` in
`number.py`. The entity validates the HA value; the policy encodes the domain
value, and its exception boundary also covers acknowledgement and accepted
state. Mode-aware control setters pass an already encoded wire string; repeating the
pending or reported value is a no-op before any block check. The load-limit policy keeps its order: reported
configuration, scheduled refresh, then mirror notification.

Characterization tests run all seven entities through the production queue for
accepted, reboot-required, rejected, uncertain, unexpected, superseded and
cancelled outcomes. Notification order, wire payloads, public errors and final
observations are fixed in `control_write_contracts.json`.
