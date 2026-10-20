# Home Assistant Automation Resilience

## Purpose of this document

Home Assistant makes it easy to combine many actions in automations. As a result, a charger can receive commands much faster, in a different order, or in states that would rarely occur when a person operates it manually from a dashboard.

That flexibility is intentional, but it creates situations such as these:

- A Start command is issued although a charging transaction is already active.
- Three different current limits are selected within a few seconds.
- A command waits for a disconnected charger and would no longer make sense several hours later.
- Two values that belong together are changed one after the other and briefly form a combination the user never intended.
- Home Assistant reports an action as successful although the charger has not confirmed it yet.

This document describes the identified failure scenarios and the safeguards implemented by the integration. All nine work items are complete. The document therefore serves both as a record of the original problems and as an explanation of why the corresponding validation, timing, queue, and reconnect rules exist in the code.

## Terms used in this document

- **Command / intent:** A change that should be sent to the charger, such as “start charging” or “use a maximum of 16 A.”
- **Write queue:** The integration does not send every command concurrently. It places commands in a queue and processes them in a controlled order.
- **Desired value:** The value most recently requested by the user. It may already be visible in Home Assistant even though the charger has not confirmed it.
- **Reported value:** The value most recently reported by the charger itself.
- **Confirmed (`confirmed`):** The charger returned a positive acknowledgement for the command.
- **Failed (`failed`):** The charger or the integration definitively rejected the command.
- **Skipped (`skipped`):** The command was deliberately not sent because it was replaced or was no longer valid when it reached the front of the queue.
- **Expired (`expired`):** The command remained queued beyond its permitted lifetime and will no longer be executed.
- **Uncertain (`uncertain`):** The integration cannot determine whether the charger received or partially applied the command. This can happen when the connection is lost immediately after sending. An uncertain result is deliberately not treated as success.

## Design principles

1. A Home Assistant action must not report success when it could not be executed.
2. The most recent user intent must not be overwritten by the result of an older request that is still in flight.
3. “Technically safe to retry” and “still wanted by the user” are separate decisions.
4. A delayed command must be validated again immediately before it is sent.
5. Desired state, charger-reported state, and command outcome must remain separate concepts.
6. Invalid or ambiguous input must be rejected explicitly instead of being silently rounded, truncated, guessed, or ignored.
7. Non-obvious timing, queue, and reconnect rules must be documented next to the code and protected by regression tests.

## Implementation status

| # | Priority | Work item | Implementation commit | Status |
|---|---|---|---|---|
| 1 | P0 | Return blocked Home Assistant actions as errors | [`bbd540c`](https://github.com/bobbesnl/growatt_thor/commit/bbd540c1f7fda8593329a149012faf9da69881e2) | Completed |
| 2 | P0 | Isolate superseded in-flight write results | [`c05f099`](https://github.com/bobbesnl/growatt_thor/commit/c05f099180f1dc22c11739da2634bfdbdc90bdb1) | Completed |
| 3 | P0 | Expire and revalidate delayed commands | [`30beb53`](https://github.com/bobbesnl/growatt_thor/commit/30beb538ea155b1ad8dde3240d3ea40157ccebcf) | Completed |
| 4 | P0 | Bind Start and Stop safely to transactions | [`62fd9d2`](https://github.com/bobbesnl/growatt_thor/commit/62fd9d29b8c20b8351dae5aee36859e7d788ba98) | Completed |
| 5 | P0 | Prevent ambiguous configuration entries and charger connections | [`3c0d57b`](https://github.com/bobbesnl/growatt_thor/commit/3c0d57b1828d60d9f3825965aaf1a7e28491d320) | Completed |
| 6 | P1 | Make paired and compound changes predictable | [`c9df462`](https://github.com/bobbesnl/growatt_thor/commit/c9df46210bdc44415042d1732f839da6a2c6dfd8) | Completed |
| 7 | P1 | Coalesce refresh and export operations | [`6d2d0b7`](https://github.com/bobbesnl/growatt_thor/commit/6d2d0b72550603834fd23b6d240ff81878f3dc6e) | Completed |
| 8 | P1 | Validate values and configuration consistently | [`d6a2af5`](https://github.com/bobbesnl/growatt_thor/commit/d6a2af547f711ed42962eecd4aed3ae59ab56b47) | Completed |
| 9 | P1 | Expose the actual outcome of a command | [`40e872a`](https://github.com/bobbesnl/growatt_thor/commit/40e872a0e98bc231534be40c5604ea2784217fbb) | Completed |

`P0` identifies cases in which the wrong state, transaction, or charger could otherwise be affected. `P1` primarily prevents misleading results, unnecessary protocol traffic, and ambiguous intermediate states.

The implementation links use permanent commit URLs in the upstream `bobbesnl/growatt_thor` repository. They become reachable on GitHub as soon as this branch history is pushed to that repository.

## 1. Return blocked Home Assistant actions as errors

### Typical scenario

An automation attempts to set the charging current to 16 A at 07:00 and then continues with another action. The charger is offline at that moment. Previously, the integration could log a warning and return normally. Home Assistant therefore considered the action successful and continued the automation even though the charger received nothing.

The same class of problem could occur when:

- Start was requested while a transaction was already active.
- A value was outside the supported range.
- A control did not apply in the current operating mode.
- The external meter was unavailable.
- A PV Linkage draft was incomplete.

### Why this was a problem

An automation can only react correctly when “successful” means that its request was actually accepted. A log entry is insufficient because the automation does not inspect the log. It might assume that charging now runs at 16 A and enable another load based on that false assumption.

### Current behavior

- Invalid values and actions that are not allowed in the current state raise a clear Home Assistant validation error.
- An unavailable charger raises a communication error.
- The relevant error messages are available in every bundled language.
- An idempotent request remains successful. If the requested value is already effective, the integration does not generate unnecessary charger traffic.
- For actions that can await a physical outcome, later rejection, replacement, expiry, or uncertainty is returned to Home Assistant instead of being presented as confirmation.

### Observable examples

- “Set current to 40 A” is rejected immediately when the entity supports no more than 32 A.
- “Start charging” is rejected when a transaction is already active.
- “Set current to 16 A” remains successful without a second OCPP write when 16 A is already confirmed.
- An unknown internal block reason fails closed with a generic error instead of producing apparent success.

## 2. Isolate superseded in-flight write results

### Typical scenario

A user moves a current slider rapidly from 13 A to 20 A and then to 17 A. The 20 A command is already in flight while the 17 A command is waiting. The charger then returns a delayed response for 20 A.

### Why this was a problem

Without additional correlation, the old response could overwrite state owned by the newer 17 A request. Home Assistant might briefly show 20 A as the current intent, or attach the rejection of 20 A to the newer 17 A change. The result of an older request would be presented as the result of the current request.

### Current behavior

- Every change to a logical configuration value receives a monotonically increasing generation. In simpler terms, every new intent has a newer version number.
- Only the current generation may update the visible desired value, pending state, or rollback state.
- The response to an older command is still considered because it may have changed the physical charger, but it cannot be presented as the outcome of the newer intent.
- An accepted superseded command schedules a safe readback so the integration can reconcile the actual charger value.
- The five most recent superseded outcomes per configuration key remain available in diagnostics without allowing the history to grow without bounds.
- Working-mode changes use the same protection even though one logical selector writes different Growatt configuration keys depending on the selected mode.

### Observable examples

- In a `13 -> 20 -> 17 A` sequence, 17 A remains the visible desired value even if the acknowledgement for 20 A arrives first.
- A rejection belonging to an older request cannot roll back the newer pending value.
- A reconnect readback reconciles the current intent rather than reviving a superseded one.

## 3. Expire and revalidate delayed commands

### Typical scenario

At 22:00 an automation requests “start charging.” The charger loses its network connection at exactly that moment and reconnects the next morning. A Start command from the previous evening must not execute unexpectedly after that reconnect.

A configuration change such as “limit current to 16 A” may reasonably survive a brief connection interruption, provided that it is still the latest intent.

### Why this was a problem

A command can be technically safe to send and still be obsolete from the user's perspective. Without an expiry policy, an old Start, Stop, or mode change could execute much later in a completely different context.

### Current behavior

Every production queue entry declares an immutable expiry and reconnect policy:

- Configuration changes remain valid for no more than five minutes. Only the latest change for the same value is retained.
- Stop remains valid for no more than 60 seconds and is bound to the exact transaction for which it was requested.
- Start and AP-mode commands remain valid for no more than 15 seconds and are discarded as soon as they encounter a disconnect.
- Every delayed command is validated again immediately before it is sent.
- A command that exceeds its lifetime receives the terminal outcome `expired`.

### Observable examples

- A Start command from the previous evening is not sent after the charger reconnects the next morning.
- A 16 A configuration change that is only a few seconds old may still be sent after a brief interruption.
- A Stop created for transaction 42 is not applied to a newer transaction 43.
- A replaced or expired request cannot roll back a newer visible value.

## 4. Bind Start and Stop safely to transactions

### Typical scenario

An automation issues Start and Stop almost simultaneously. In another case, it issues Stop while the charger changes from `Charging` to `SuspendedEV`. Those states look different, but both still belong to an active transaction.

### Why this was a problem

Start and Stop must not remain as unrelated commands in the queue for an arbitrary amount of time. Otherwise, the integration could stop first and later resume charging because an old Start was still waiting. More seriously, a Stop with an invented transaction ID `0` or a stale Stop applied to a newer transaction could affect the wrong charging session.

### Current behavior

- `Charging`, `SuspendedEV`, and `SuspendedEVSE` are consistently treated as active transaction states.
- Start and Stop share one logical queue lane, so opposing unsent intents cannot remain queued independently and execute later in an obsolete order.
- Stop can cancel a matching Start only while that Start is still in the local queue and is therefore definitely unsent.
- A Start that has already entered OCPP execution is outside the local cancellation boundary because the charger may already have received it.
- Stop is sent only with a known transaction ID. The integration never invents transaction ID `0`.
- Immediately before execution, Stop requires both an active transaction and an exact match with the transaction ID captured when the action was created.
- The supersession rule is deliberately asymmetric: Start is rejected while a transaction is active and therefore cannot erase a valid queued Stop. Once the previous transaction has ended, a newly valid Start may replace that transaction's stale unsent Stop.

### Observable examples

- Start is rejected in every active charging state, not only in `Charging`.
- No OCPP Stop is sent when no transaction ID is known.
- If transaction 42 ends during a disconnect, its queued Stop is not later sent against transaction 43.
- A Stop can cancel a definitely unsent Start locally without creating an unnecessary OCPP Stop request.

## 5. Prevent ambiguous configuration entries and charger connections

### Typical scenario

Home Assistant accidentally contains two configuration entries for the integration. Alternatively, a second charger with a different charge-point identity connects to the same endpoint. Without an explicit ownership model, the second runtime or connection could replace the first one in domain-global state.

Another edge case occurs when the same physical charger reconnects before its old network connection has completely shut down.

### Why this was a problem

An action such as “stop charging” must unambiguously target one charger and one current connection. After a reconnect, an old socket must neither publish state nor remove the replacement connection during its own cleanup.

### Current behavior in the 1.7 line

- Exactly one configuration entry is permitted. A second setup attempt is aborted with a translated, explicit reason.
- Runtime ownership is enforced independently of the config-flow guard, so duplicate legacy entries or concurrent setup calls cannot replace the active coordinator.
- Unload and failed-setup cleanup are ownership-aware. A rejected or stale entry cannot stop the server or clear state belonging to the active entry.
- The first connected charge-point identity remains bound for the lifetime of the loaded entry.
- The same charger may reconnect. A different charge-point identity receives a controlled OCPP policy close and cannot inherit the existing entities, transactions, or session data.
- Deliberately replacing the physical charger requires reloading the integration, which establishes a new runtime identity boundary.
- A same-charger reconnect publishes the replacement socket as owner before closing the older socket.
- Every inbound OCPP handler verifies socket-object ownership. `StartTransaction` repeats this check after waiting for the transaction-ID allocator so an old socket cannot consume authorization or commit transaction state during that race.
- Responses from a superseded socket do not update current runtime state. An integration-initiated write that may already have reached the old socket remains `uncertain` and is not blindly repeated on the replacement socket.

### Observable examples

- A second configuration entry cannot stop the active server or replace its coordinator.
- Charger `THOR-1` may reconnect, but `THOR-2` cannot silently take over its entities and transaction state.
- The delayed finalizer of the old `THOR-1` socket cannot remove the new `THOR-1` connection.
- A superseded socket cannot publish meter values, timeout counters, configuration readbacks, or transaction updates.

### Deliberate limitation

This does not implement true multi-charger support. That feature requires runtime data to be modeled explicitly per configuration entry and charge-point identity. Until then, an explicit rejection is safer than ambiguous routing.

## 6. Make paired and compound changes predictable

### Typical scenario A: two related schedule values

An automation sets the Auto Charge start time to 01:00 and immediately sets the end time to 06:00. If both changes are transmitted independently, the first write can briefly contain the new start time combined with the old end time. The user never requested that intermediate schedule.

### Typical scenario B: PV Linkage Apply

Applying PV Linkage consists of multiple physical writes. The charger may confirm the first step and reject the second, or the connection may be lost between the two steps. The logical operation is then neither a complete success nor a complete failure.

### Current behavior

- Auto Charge start and end times share a 500 ms debounce task. Back-to-back edits settle before one final combined `G_AutoChargeTime` value is built and sent.
- A second edit cancels the first task only while it is still sleeping. Integration unload cancels a remaining debounce task, and unexpected background failures are logged explicitly.
- PV Linkage Apply records both the number of acknowledged physical steps and one explicit logical result: `success`, `failed`, `partial`, or `uncertain`.
- A disconnect before any acknowledgement remains safe for the queue to retry. A disconnect after an accepted step cannot replay the whole compound operation and is retained as partial progress.
- A later-step rejection, lost acknowledgement, or other uncertain failure leaves the draft visibly dirty and schedules a coalesced readback of readable charger configuration.
- The integration does not attempt a synthetic rollback because that would introduce another independently fallible OCPP write.
- A successful Apply clears only the exact draft snapshot that was sent. Changes made while an older Apply is in flight remain pending.
- The Apply button exposes the latest result as `last_apply`, and the same structured progress is retained in diagnostics.

### Observable examples

- Rapidly setting 01:00 and 06:00 produces one final combined schedule rather than an unintended intermediate schedule.
- If the second PV write is rejected, the draft remains dirty and the logical result is not `success`.
- If the connection is lost after one accepted step, the full operation is not replayed and its partial or uncertain state remains visible.
- An edit made while Apply is running is not cleared when the older draft finishes successfully.

## 7. Coalesce refresh and export operations

### Typical scenario

Several dashboards open at once while an automation also calls `growatt_thor.refresh` repeatedly. Without coalescing, each caller would append a complete Status, External Meter, and Configuration sequence. An important write could then wait behind a backlog of diagnostic reads.

Similarly, two automations may request an export to the same CSV destination at the same time.

### Why this was a problem

The OCPP request lock prevented simultaneous protocol messages, but it did not prevent a long queue of identical refresh sequences. Service failures were also sometimes visible only in the log, so the calling automation could not reliably detect that refresh or export had failed.

### Current behavior

- Concurrent refresh callers share one single-flight task and therefore one physical refresh sequence.
- Cancelling one caller does not cancel the shared operation for other callers.
- Every refresh read participates in a two-stage write-priority check. If a charger write is already pending or appears between refresh steps, the remaining optional reads are not started.
- A missing, unloaded, or disconnected charger raises a translated Home Assistant communication error. Failed refresh steps and export I/O failures are also returned to the caller instead of being logged only.
- Domain services are registered once during integration setup and are not removed with one config-entry unload. During reload, historical session export remains available while live refresh fails clearly until the runtime connection is available again.
- Concurrent exports to the same normalized destination path share one task, executor job, and notification.
- CSV output is assembled in a temporary file beside the destination and atomically replaces the old file only after successful completion.

### Observable examples

- Twenty concurrent refresh callers produce one Status, External Meter, and Configuration sequence rather than twenty sequences.
- A current-limit write requested during refresh does not wait behind every remaining optional diagnostic read.
- A failed export preserves an existing complete CSV file.
- When no session log exists, the export produces a valid header-only CSV rather than a broken download link.
- Malformed export dates are rejected before the integration resolves a target path or starts file I/O.

## 8. Validate values and configuration consistently

### Typical scenario

A template produces `6.6` A although the entity supports only whole-ampere steps. Another automation produces `NaN` through a calculation. A user accidentally enters TCP port `70000`, or supplies an export end date that is earlier than its start date.

### Why this was a problem

Silent rounding or truncation changes user intent. Without a visible error, 6.6 A could become 7 A. Non-finite numbers can produce invalid OCPP payloads during formatting. Individually valid values can also form an invalid combination, such as a reversed date range.

### Current behavior

- `NaN`, positive infinity, and negative infinity are rejected before any write is queued or formatted.
- Bounds and step size are checked exactly. A value is not silently rounded to a different valid value.
- Solar import limit, power-meter address, and Smart Boost payload builders repeat the relevant validation immediately before wire formatting. This preserves the safety boundary even if a future code path bypasses entity-level validation.
- Decimal formatting removes only fractional zeroes, so an upper bound such as `200` cannot accidentally become `2`.
- Invalid charger readbacks are excluded from unchanged-value and rollback decisions.
- TCP ports must be whole values in the inclusive range `1..65535`.
- Polling intervals must be finite whole seconds at or above the defined safety minimum.
- A polling-interval option change takes effect at runtime. It wakes an existing wait and starts the new cadence from the save time, while an update received during OCPP polling work is retained for the next wait.
- Export dates are checked for both valid format and the logical rule that the start date must not be later than the end date.

### Observable examples

- `6.6 A` is rejected for a 1 A step instead of being rounded to 7 A.
- `NaN`, `+inf`, and `-inf` never reach an OCPP payload.
- Port `65535` is accepted, while port `65536` is rejected.
- A numeric string may be normalized deliberately, but `10.5` is not silently truncated to `10`.
- An export from the twentieth to the tenth of the same month is rejected with a clear validation error.
- A new polling interval affects the next polling cycle without requiring an integration reload.

## 9. Expose the actual outcome of a command

### Typical scenario

An automation changes the charging current and immediately enables another load. Previously, awaiting `queue_write(...)` meant only that the command had been enqueued. It did not mean that the charger had confirmed it. The write could still be waiting for rate limiting, a reconnect, acknowledgement, or readback.

### Why this was a problem

An optimistically displayed entity value is not physical confirmation. Without a separate completion signal, an automation could not distinguish enqueueing a command from successfully executing it on the charger.

### Current behavior

- Every queued intent receives a UUID command ID and an immutable completion handle that resolves exactly once.
- Public terminal outcomes are `confirmed`, `failed`, `skipped`, `expired`, and `uncertain`.
- Suitable Home Assistant actions wait up to 30 seconds for that terminal result. Start, Stop, PV Linkage Apply, AP mode, direct configuration controls, working mode, numeric configuration entities, and direct switches use this path.
- If the 30-second wait expires, Home Assistant reports that the command is still pending. The physical command is not cancelled and may still complete normally later.
- Cancelling the caller's wait likewise does not silently cancel a physical command that may already be in progress.
- The diagnostic **Last command result** sensor publishes the terminal state, command ID, command name, detailed write status, timestamps, reason, and charger result. The same structured record is included in config-entry diagnostics, and queue logs contain the command ID for correlation.
- Replacement, explicit cancellation, expiry, revalidation failure, callback failure, missing legacy callback results, lost acknowledgements, partial compound writes, and integration unload all resolve through one central completion path.
- During unload, an active request becomes `uncertain` because it may already have reached OCPP, while work that was still queued becomes `skipped`.

### Auto Charge exception

The paired Auto Charge time values deliberately wait 500 ms for each other. By the time the combined write begins, the original Home Assistant caller no longer exists. Its eventual outcome is therefore exposed through **Last command result** rather than returned to either individual time edit.

### Observable examples

- A charger rejection can no longer appear as a successful Home Assistant action.
- A command replaced by a newer intent resolves exactly once as `skipped`.
- A timeout after 30 seconds does not mean “failed” and does not remove the command. Its command ID allows the later result to be correlated in the result sensor and logs.
- A PV Linkage operation with only some acknowledged steps maps conservatively to public outcome `uncertain`, while the detailed internal result `partial` remains available for diagnostics.

## Deliberate boundaries and guidance for automations

- A network connection lost immediately after sending cannot always be resolved conclusively. In that case, `uncertain` is more accurate than an invented success or failure.
- A 30-second action timeout ends only the Home Assistant caller's wait, not the physical command.
- An optimistic entity value represents the latest desired value. Automations that require physical confirmation must use the command outcome rather than optimistic state alone.
- Rapid changes to the same value may replace older changes that are definitely still unsent. This is intentional: the integration should apply the latest meaningful intent instead of replaying an obsolete sequence of slider movements.
- The 1.7 line deliberately does not support multiple physical chargers in one shared runtime context.

## Test and documentation expectations

Each of the nine areas is protected by focused regression tests. The covered cases include rapid intent changes, disconnects, reconnects, expiry, timeouts, concurrent service calls, stale sockets, partial acknowledgements, queue replacement, and integration reloads.

Timing, safety, ownership, and reconnect rules that are not obvious from the code alone are also documented with inline comments at the relevant implementation site. The goal is not the shortest possible code; it is behavior that another maintainer can understand and change safely long after the original implementation work.
