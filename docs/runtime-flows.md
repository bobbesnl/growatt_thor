# Runtime flows

[Documentation](../README.md#documentation) · [Architecture](architecture.md) · [Start reading the code](CONTRIBUTING.md)

These diagrams follow four common paths through the code. They show who owns each
step and where a Home Assistant action finishes. Terms are explained in the
[glossary](architecture.md#glossary); timeout, replacement and reconnect rules are
described in [automation resilience](automation-resilience.md).

Three distinctions run through all of them:

- **Queued, sent and confirmed are different states.** An HA action that waits
  for a command finishes with the queue's terminal result, not with a later
  charger observation.
- **Only the write queue sends charger writes.** Entities, services, targets and
  the stop guard enqueue work; the queue rebinds the current charge point and
  revalidates the intent immediately before sending.
- **Observations arrive separately.** `StartTransaction`, `StopTransaction`,
  `StatusNotification`, `MeterValues` and Growatt records update the coordinator
  whenever the charger sends them, independent of any command.

## Start charging

```mermaid
sequenceDiagram
  autonumber
  actor User as User or automation
  participant Button as StartChargingButton
  participant Ctl as GrowattOcppCharger
  participant Cmd as StartChargingCommand
  participant Queue as ChargerWriteQueue
  participant CP as GrowattChargePoint
  participant THOR
  participant Coord as Coordinator / SessionLifecycle

  User->>Button: press
  Button->>Ctl: async_start()
  Ctl->>Cmd: async_request()
  Cmd->>Cmd: reject if target needs reconciliation,<br/>disconnected, faulted or transaction active
  Cmd->>Queue: enqueue(priority, Start/Stop lane, revalidate)
  Queue->>Queue: wait for connection, rebind current charge point,<br/>revalidate
  Queue->>Cmd: _start_charging(charge point)
  Cmd->>CP: remote_start_transaction(connector 1)
  CP->>CP: create one-shot HA start grant
  CP->>THOR: RemoteStartTransaction
  THOR-->>CP: Accepted / Rejected
  CP-->>Cmd: status
  Cmd-->>Queue: success, failed or uncertain
  Queue-->>Button: terminal command result
  Button-->>User: action returns or raises
  Note over Cmd,CP: Two seconds later: TriggerMessage(StatusNotification)<br/>on whichever connection is current
  THOR->>CP: StartTransaction
  CP->>Coord: allocate transaction ID, recheck socket ownership,<br/>authorization.decide() consumes the grant
  Coord->>Coord: start_transaction(): session state, event tracking,<br/>transaction hooks
  CP-->>THOR: transactionId and idTagInfo
  THOR->>CP: MeterValues …
  CP->>Coord: process_meter_values()
```

Code: [`charging/growatt_charger.py`](../custom_components/growatt_thor/charging/growatt_charger.py),
[`charging/commands.py`](../custom_components/growatt_thor/charging/commands.py),
[`runtime/charger_write_queue.py`](../custom_components/growatt_thor/runtime/charger_write_queue.py),
[`ocpp/server.py`](../custom_components/growatt_thor/ocpp/server.py),
[`sessions/runtime.py`](../custom_components/growatt_thor/sessions/runtime.py).

A rejected or failed request revokes the one-shot grant. An uncertain request
keeps it for its short lifetime, because the charger may still send the
matching `StartTransaction`.

## Stop charging

```mermaid
sequenceDiagram
  autonumber
  actor Source as Stop button or stop guard
  participant Cmd as StopChargingCommand
  participant Queue as ChargerWriteQueue
  participant CP as GrowattChargePoint
  participant THOR
  participant Life as SessionLifecycle

  Source->>Cmd: async_request()
  Cmd->>Queue: cancel unsent Start in the Start/Stop lane
  alt Start was cancelled and no transaction is active
    Cmd-->>Source: done, nothing to stop
  else transaction active
    Cmd->>Queue: enqueue(priority, bound to transaction ID,<br/>optional guard recheck)
    Queue->>Cmd: _stop_charging() after revalidation
    Cmd->>Life: record_stop_requested(reason)
    Cmd->>CP: remote_stop_transaction(transaction ID)
    CP->>THOR: RemoteStopTransaction
    THOR-->>CP: Accepted / Rejected
    Cmd-->>Queue: terminal result
    Queue-->>Source: action returns or raises
  end
  THOR->>CP: StopTransaction
  CP->>Life: stop_transaction()
  Life->>Life: ignore unless it matches the active transaction
  Life->>Life: snapshot transaction, reconcile site accounting,<br/>retain pending completion, reset live values
  Life->>Life: save storage, notify transaction hooks
  CP-->>THOR: StopTransaction.conf without idTagInfo
```

Code: [`charging/commands.py`](../custom_components/growatt_thor/charging/commands.py),
[`energy/stop_guard.py`](../custom_components/growatt_thor/energy/stop_guard.py),
[`sessions/runtime.py`](../custom_components/growatt_thor/sessions/runtime.py).

A Stop is tied to the transaction it was created for. If a different
transaction is active when the queue reaches it, the command is skipped. The
stop guard adds its own recheck so a condition that cleared while waiting does
not stop charging.

## Write a configuration value

The example is the maximum current. Other configuration entities differ in
their rollback and readback details; see
[configuration write behavior per entity](invariants.md#configuration-write-behavior-per-entity).

```mermaid
sequenceDiagram
  autonumber
  actor User as User or automation
  participant Entity as MaxCurrentNumber
  participant Coord as Coordinator
  participant Queue as ChargerWriteQueue
  participant CP as GrowattChargePoint
  participant THOR

  User->>Entity: set 16 A
  Entity->>Entity: validate range, block reasons and connection,<br/>return early if 16 A is already reported
  Entity->>Coord: show 16 A optimistically
  Entity->>Coord: begin_configuration_write() → generation
  Entity->>Queue: enqueue(dedupe key G_MaxCurrent, rate limited)
  Note over Queue: An unsent older intent for the same key is replaced
  Queue->>Queue: wait for connection and write spacing,<br/>pause polling before the write
  Queue->>Entity: _write_to_thor(value, previous, generation)
  Entity->>CP: change_configuration("G_MaxCurrent", "16")
  CP->>THOR: ChangeConfiguration
  THOR-->>CP: Accepted / RebootRequired / Rejected
  Entity->>Coord: acknowledge_configuration_write(generation)
  alt accepted and still the current generation
    Entity->>Coord: apply reported value
  else rejected
    Entity->>Coord: restore last reported value if still current
  end
  Entity->>Coord: schedule_configuration_refresh()
  Entity-->>Queue: terminal result
  Queue-->>User: action returns or raises
  Coord->>CP: later: one coalesced GetConfiguration readback
```

Code: [`number.py`](../custom_components/growatt_thor/number.py),
[`configuration/controls.py`](../custom_components/growatt_thor/configuration/controls.py),
[`coordinator.py`](../custom_components/growatt_thor/coordinator.py).

For the number entities, an uncertain write marks the generation as uncertain and
requests the readback immediately instead of guessing the charger's value.

## Complete a session

```mermaid
sequenceDiagram
  autonumber
  participant THOR
  participant CP as GrowattChargePoint
  participant Life as SessionLifecycle
  participant Outbox as SessionOutbox
  participant Store as HA storage
  participant CSV as Session history (CSV)

  THOR->>CP: StopTransaction
  CP->>Life: stop_transaction()
  Life->>Store: save checkpoint with pending completion
  THOR->>CP: DataTransfer frozenrecord / currentrecord
  CP->>Life: process_session_record(record)
  Life->>Life: match pending completion, skip duplicates,<br/>keep invalid records without applying them
  Life->>Life: correlate with the OCPP transaction,<br/>merge events, update last session and totals,<br/>reconcile accounting
  Life->>Outbox: enqueue(session row)
  Life->>Life: drop the matched pending completion
  par background tasks
    Life->>Store: save storage
  and
    Life->>Outbox: flush
    Outbox->>Store: save checkpoint (row still pending)
    Outbox->>CSV: append row (history lock and recovery journal)
    Outbox->>Store: save checkpoint (row acknowledged)
  end
```

Code: [`sessions/runtime.py`](../custom_components/growatt_thor/sessions/runtime.py),
[`sessions/outbox.py`](../custom_components/growatt_thor/sessions/outbox.py),
[`sessions/csv.py`](../custom_components/growatt_thor/sessions/csv.py),
[`sessions/history_store.py`](../custom_components/growatt_thor/sessions/history_store.py).

If the CSV append fails, the row stays in the checkpoint and is retried on
setup, after later completions and at shutdown. Session IDs make a repeated
append harmless. See [persistent completion](architecture.md#persistent-completion)
for limits and backup advice.
