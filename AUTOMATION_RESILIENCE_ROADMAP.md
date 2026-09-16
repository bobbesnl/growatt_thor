# Home Assistant Automation Resilience Roadmap

## Purpose

Home Assistant users can combine the Growatt THOR entities in automations that
issue commands much faster, in a different order, or in charger states that a
person using the dashboard would rarely produce. This roadmap records the
defensive behaviour needed to keep those automations predictable without
hiding mistakes or sending stale commands to the charger.

The priorities in this document are based on safety and observability:

- **P0** prevents an action from affecting the wrong state, transaction, or
  charger.
- **P1** prevents misleading results, unnecessary OCPP traffic, and ambiguous
  partial state.
- **P2** improves diagnostics and long-term maintainability.

## Design principles

1. A Home Assistant action must not report success when it was rejected before
   reaching the charger.
2. The latest user intent must not be overwritten by the result of an older
   in-flight request.
3. "Safe to retry" and "still wanted" are separate decisions.
4. Every delayed command must be validated again immediately before execution.
5. Reported charger state, desired state, and command outcome remain separate.
6. Invalid or ambiguous input is rejected explicitly instead of being silently
   rounded, guessed, or ignored.
7. Non-obvious queue and reconnect decisions are documented next to the code
   and covered by regression tests.

## Delivery status

| # | Priority | Work item | Status |
|---|---|---|---|
| 1 | P0 | Return blocked Home Assistant actions as errors | In progress |
| 2 | P0 | Isolate superseded in-flight write results | Completed |
| 3 | P0 | Expire and revalidate delayed commands | Completed |
| 4 | P0 | Harden Start/Stop transaction semantics | Completed |
| 5 | P0 | Prevent ambiguous config entries and charger connections | Completed |
| 6 | P1 | Make paired and compound changes predictable | Completed |
| 7 | P1 | Coalesce manual refresh and harden integration services | Completed |
| 8 | P1 | Tighten value and config-entry validation | Completed |
| 9 | P1 | Expose a reliable command completion signal | Planned |

## 1. Return blocked Home Assistant actions as errors

**Problem:** Several entity methods currently log a warning and return normally
when an action is blocked. Home Assistant consequently considers the service
call successful, so an automation continues even though nothing was queued.

Examples include a disconnected or faulted charger, an active transaction, a
control that does not apply in the current mode, an unsupported current, an
unavailable external meter, and an incomplete PV Linkage draft.

**Target behaviour:**

- Raise `ServiceValidationError` when the request is invalid in the current
  state or contains an invalid value.
- Raise `HomeAssistantError` when the charger connection is unavailable.
- Provide translated exception keys in every bundled language.
- Keep idempotent requests successful: setting an already effective value is
  not an error.
- Keep the write queue asynchronous for now. Reporting a rejection or uncertain
  result that happens after enqueueing depends on the completion mechanism in
  item #9 and the expiry rules in item #3.

**Acceptance tests:**

- Every known write-block reason maps to the intended HA exception class and a
  stable translation key.
- Unknown internal block reasons fail closed with a generic translated error.
- Translation files contain identical exception keys and placeholders.
- Public entity methods no longer silently accept the covered blocked actions.

## 2. Isolate superseded in-flight write results

**Problem:** Queue deduplication replaces waiting entries, but an older request
that is already executing can still update the state owned by a newer request
for the same configuration key. A rapid `13 -> 20 -> 17 A` sequence can
therefore temporarily attach the `20 A` acknowledgement or rejection to the
newer `17 A` intent.

**Target behaviour:**

- Assign a monotonically increasing generation or request ID per logical key.
- Allow every response to update confirmed charger state where appropriate.
- Allow only the current generation to update desired state, pending state, or
  rollback state.
- Record superseded outcomes for diagnostics without presenting them as the
  result of the latest action.

**Acceptance tests:**

- Older accepted, rejected, uncertain, and failed writes cannot overwrite a
  newer pending value.
- A newer queued write remains visible while an older write completes.
- Reconnect readback reconciles the current generation only.

**Implemented on 2026-09-15:**

- Every `ChangeConfiguration` intent now receives a monotonically increasing
  generation per configuration key; the queue carries the key and generation
  as one inseparable pair.
- A callback may update pending, desired, or rollback state only while it still
  owns the current generation. Older accepted outcomes still schedule a safe
  readback because they may briefly have changed the physical charger.
- Working-mode changes also carry an entity-level intent token because one
  logical mode selector writes different Growatt keys depending on the chosen
  mode.
- The five latest superseded outcomes per key remain available in diagnostics
  without replacing the current write state or growing without bounds.
- Burst tests hold the first request in flight, queue a replacement, and prove
  that the older acknowledgement cannot overwrite the newer visible value.

## 3. Expire and revalidate delayed commands

**Problem:** A definitely unsent command can currently remain queued for an
unbounded time. Retrying after reconnect is transport-safe, but the original
intent may no longer be current hours later.

**Target behaviour:**

- Add an explicit expiry and reconnect policy to every queue entry.
- Configuration changes retain last-value-wins semantics for a bounded time.
- Start and AP-mode commands expire quickly and never execute as a surprise
  after a long reconnect.
- Stop commands remain tied to the transaction they were created for.
- Expired commands receive a terminal `expired` outcome.

**Acceptance tests:**

- Expired commands never reach OCPP.
- Replaced and expired entries cannot change current pending state.
- A short reconnect can retain an eligible command; a long reconnect cannot.

**Implemented on 2026-09-15:**

- Every production queue entry now declares an immutable expiry/reconnect
  policy. Configuration writes retain last-value-wins behavior for up to five
  minutes, Stop commands for up to 60 seconds, and Start/AP-mode commands for
  no more than 15 seconds.
- Start and AP-mode actions are discarded as soon as they encounter a
  disconnect. Configuration and transaction-bound Stop commands may cross only
  a short disconnect and are never sent after their monotonic deadline.
- Queue entries are revalidated before execution. Start cannot run after a
  transaction became active, while Stop remains bound to the exact transaction
  ID captured by the original action and no longer invents transaction ID `0`.
- Expired configuration writes receive the terminal `expired` state. Replaced
  and expired generations run guarded cleanup, so neither an old rollback nor
  an entity-local optimistic value can overwrite the latest automation intent.
- Regression tests cover expiry while disconnected and behind an active write,
  short reconnect retention, volatile disconnect handling, superseded cleanup,
  terminal configuration state, and explicit policy wiring at every call site.

## 4. Harden Start/Stop transaction semantics

**Problem:** Start and Stop need to remain coherent when automations invoke them
around transaction state transitions or queue both opposing intents.

**Target behaviour:**

- Use the shared `transaction_is_active` decision for Remote Start.
- Check Start and Stop both when queued and immediately before execution.
- Never invent transaction ID `0`.
- Bind Stop to the expected transaction ID and skip it if that transaction has
  ended or changed.
- Define how opposite pending Start and Stop intents supersede each other.

**Acceptance tests:**

- Start is rejected in every active OCPP transaction state.
- Stop without a known transaction ID does not issue an OCPP call.
- A stale Stop cannot affect a newer transaction after reconnect.

**Implemented on 2026-09-15:**

- Remote Start and Remote Stop now share one logical queue lane. Opposing
  commands can no longer remain queued independently and execute later in an
  order that no longer represents the latest valid automation intent.
- Stop explicitly cancels a matching Start only while that Start is still in
  the local queue and therefore definitely unsent. If no transaction is active,
  that cancellation completes locally without inventing transaction ID `0` or
  sending an unnecessary OCPP Stop; it also remains available if the charger
  disconnected after the Start was queued.
- An OCPP request already being executed is deliberately outside the local
  cancellation boundary. Home Assistant does not claim such a Start was
  retracted because the charger may already have received it.
- The supersession rule is intentionally asymmetric: Start is rejected while
  any retained coordinator state indicates an active transaction, so it cannot
  erase a valid queued Stop. Once the previous transaction has ended, a newly
  valid Start may replace that transaction's now-stale unsent Stop.
- Start and Stop validity rules live in small pure functions and are applied
  again immediately before OCPP execution. A delayed Stop requires both an
  active transaction and an exact match with its originally captured ID.
- Regression tests cover all three active OCPP statuses (`Charging`,
  `SuspendedEV`, and `SuspendedEVSE`), retained partial transaction state,
  unsent Start cancellation, the in-flight cancellation boundary, opposing
  intent replacement, ended transactions, and changed transaction IDs.

## 5. Prevent ambiguous config entries and charger connections

**Problem:** Runtime data is currently stored in one domain-global slot. A
second config entry or a second charge point can replace the coordinator or
active connection and make an action operate on an ambiguous device.

**Target behaviour for the 1.7 line:**

- Permit one config entry until multi-charger support is intentionally modeled.
- Retain the active charge-point identity for the current entry.
- Reject a simultaneous connection with a different charge-point identity.
- Never let a superseded connection update the current coordinator.

**Later option:** Store all runtime data per config entry and route charge-point
identities explicitly when true multi-charger support is designed.

**Acceptance tests:**

- A second config entry is rejected with a clear flow error.
- A second charger cannot replace an active, different charger.
- Disconnect cleanup from an old socket cannot affect the current connection.

**Implemented on 2026-09-16:**

- The config flow now aborts before showing a second setup form, using the
  localized `single_instance_allowed` reason in every bundled language. The
  runtime independently claims the first entry as its owner, so duplicate
  legacy entries or concurrent setup calls cannot bypass the UI guard and
  replace the global coordinator.
- Unload and failed-setup cleanup are ownership-aware. A rejected or stale
  config entry cannot stop the server or clear state belonging to the active
  entry, while a failed owner releases its claim so a later retry can succeed.
- The first charger ID connected during one loaded-entry lifetime is retained.
  The same charger may reconnect, but a different ID receives an OCPP policy
  close and cannot inherit existing entities, transactions, or session data.
  Intentionally replacing the physical charger therefore requires reloading
  the integration, which starts a fresh runtime identity boundary.
- A same-charger reconnect publishes the replacement socket as owner before
  closing the older socket. Every inbound OCPP handler verifies socket-object
  ownership, and `StartTransaction` repeats that check after waiting for the
  transaction-ID allocator so the old socket cannot consume authorization or
  commit transaction state during the race.
- Integration-initiated OCPP calls now discard a result if their socket was
  superseded while the request was in flight. Such writes remain non-retryable
  and uncertain rather than being repeated on the new socket; read responses
  and timeout counters likewise cannot update the replacement's coordinator.
- Watchdog and connection-finalizer cleanup release the active slot by object
  identity. Regression tests cover entry claims, translated aborts, first
  connection, same-ID reconnects, different-ID rejection, retained identity,
  in-flight responses, stale inbound messages, and superseded disconnects.

## 6. Make paired and compound changes predictable

**Problem:** Setting Auto Charge start and stop times back-to-back can send one
intermediate schedule containing one new and one old value. PV Linkage applies
multiple physical writes and can stop after a partial success without exposing
that state clearly.

**Target behaviour:**

- Debounce paired Auto Charge edits or stage them behind an explicit Apply.
- Optionally provide one action that accepts the complete schedule atomically
  from Home Assistant's perspective.
- Record compound writes as `success`, `failed`, `partial`, or `uncertain`.
- Always read back readable configuration after a partial compound result.
- Never clear a draft unless the complete logical operation succeeded.

**Acceptance tests:**

- A back-to-back start/stop update emits one final schedule payload.
- A rejected second PV write retains the draft and schedules readback.
- A partial result is visible in diagnostics and is not reported as success.

**Implemented on 2026-09-16:**

- Auto Charge start and stop now share one 500 ms debounce task. A second
  entity edit cancels the still-sleeping first task, and the final combined
  `G_AutoChargeTime` value is built only after both pending values have
  settled. Integration unload cancels the task, and unexpected background
  failures are logged explicitly instead of becoming unobserved task errors.
- PV Linkage Apply now records both the number of acknowledged physical steps
  and one explicit logical outcome: `success`, `failed`, `partial`, or
  `uncertain`. A disconnect before any acknowledgement remains safe for the
  queue to retry, while a disconnect after an accepted step cannot replay the
  complete compound operation and is retained as partial progress.
- A rejected later step, a lost acknowledgement, or another uncertain failure
  keeps the user's draft dirty and schedules a coalesced immediate readback of
  readable configuration. The integration does not attempt a synthetic
  rollback because that would add another independently fallible OCPP write.
- A complete Apply clears only the exact draft snapshot that was sent. Changes
  made while an older Apply is in flight therefore remain visibly pending even
  after every step of the older snapshot was accepted.
- The Apply button exposes the latest result as `last_apply`, and diagnostics
  retain the same structured progress under `compound_writes.pv_linkage`.
  Queue logging has a separate partial branch and never labels it as success.
- Regression tests cover the settled paired schedule, debounce cancellation
  and failure logging, first- and second-step rejection, Manual and Smart
  partial applies, safe pre-write retry, post-success disconnect, lost
  acknowledgement, exact-draft cleanup, readback scheduling, and partial
  queue logging.

## 7. Coalesce manual refresh and harden integration services

**Problem:** Repeated `growatt_thor.refresh` calls are serialized at the OCPP
layer but can still build a backlog of complete refresh sequences. Service
errors are logged rather than returned to the calling automation.

**Target behaviour:**

- Implement refresh as a single-flight operation shared by concurrent callers.
- Give pending writes priority over manually requested diagnostic reads.
- Return communication failures to Home Assistant.
- Register integration services once and keep their behaviour defined while an
  entry is temporarily unloaded.
- Serialize or deduplicate exports that target the same output file.

**Acceptance tests:**

- Many concurrent refresh calls create one OCPP refresh sequence.
- A write queued during refresh gets the documented priority.
- Disconnected and failed refresh actions return HA errors.

**Implemented on 2026-09-16:**

- Manual refresh now uses a single-flight task. Concurrent dashboards,
  scripts, and automations await the same Status, External Meter, and
  Configuration sequence instead of appending duplicate sequences behind the
  OCPP request lock. Cancelling one caller does not cancel the shared physical
  operation for the remaining callers.
- Every manual-refresh read participates in the existing two-stage write
  priority check. If a charger write is already pending or appears between
  refresh steps, the remaining optional reads are not started and the service
  reports which step could not complete. The integration does not silently
  retry and move those reads back in front of the user write.
- A missing, unloaded, or disconnected charger now raises the translated
  `charger_disconnected` Home Assistant error. Failed refresh steps and export
  I/O failures likewise return localized service errors instead of only
  writing a log line, while malformed export dates return a validation error.
- Domain services are registered once during integration setup and are no
  longer removed with one config-entry unload. Their behaviour during reload
  is explicit: historical session export remains usable, while charger refresh
  fails clearly until the runtime connection is available again.
- Concurrent exports for the same normalized destination path share one task,
  executor job, and notification. CSV output is assembled in a temporary file
  beside the destination and atomically replaced, so a failure preserves the
  previous complete export; an absent session log produces a valid header-only
  export instead of a broken download link.
- Regression tests cover 20 concurrent refresh callers, caller cancellation,
  write priority before and between refresh steps, disconnected and failed
  refreshes, explicit retry, same-target export deduplication, failed-export
  retry, atomic replacement, empty exports, service lifetime wiring, translated
  errors, and all-language translation structure.

## 8. Tighten value and config-entry validation

**Problem:** Some values are silently rounded, non-finite numbers are not
rejected everywhere, and several config or service fields lack cross-field
validation.

**Target behaviour:**

- Reject `NaN`, positive infinity, and negative infinity before formatting.
- Validate bounds and step size without unexpected coercion.
- Validate TCP ports as `1..65535`.
- Validate export date order as well as date format.
- Apply a changed poll interval to the running poller or explicitly reload the
  entry.

**Acceptance tests:**

- No non-finite or out-of-range value reaches an OCPP payload.
- Invalid dates and reversed ranges return validation errors.
- A changed poll interval affects the next polling cycle predictably.

**Implemented on 2026-09-16:**

- Number actions now share one exact decimal validation boundary. `NaN`, both
  infinities, values outside the entity range, and values that do not match the
  advertised step are rejected with translated Home Assistant validation
  errors before pending state, optimistic state, or a write-queue entry is
  created. User values are no longer silently rounded to a different intent.
- Solar import limit, power-meter address, and Smart Boost payload builders
  repeat the relevant finite, range, and step checks immediately before wire
  formatting. Decimal formatting removes only fractional zeroes, so an upper
  bound such as `200` cannot accidentally become `2`. Invalid charger
  readbacks are likewise excluded from unchanged-value and rollback decisions.
- Config-flow and persisted-entry validation now accept only exact TCP ports in
  `1..65535` and finite whole-second polling intervals at or above the safety
  minimum. Numeric strings are normalized deliberately; fractional values are
  not truncated.
- The running external-meter poller uses a wakeable schedule. Saving a changed
  interval interrupts an existing wait and starts the new cadence from the
  save time; an update that arrives while OCPP poll work is executing is
  retained rather than lost before the next wait.
- Session exports distinguish malformed dates from a reversed inclusive date
  range and reject both before resolving a target path or starting an executor
  job. All bundled translations expose the same validation keys and
  placeholders.
- Regression tests cover non-finite values, exact bounds and steps, direct
  encoder bypasses, Smart Boost formatting, read/write ordering, protocol port
  limits, live option application, poll-update races, malformed dates,
  reversed ranges, and translation structure.

## 9. Expose a reliable command completion signal

**Problem:** `await queue_write(...)` currently waits only until the command is
enqueued. An automation can continue while the physical write is still waiting
for rate limiting, reconnect, acknowledgement, or readback.

**Target behaviour:**

- Give each queued command a completion future and stable command ID.
- Define terminal outcomes: `confirmed`, `failed`, `skipped`, `expired`, and
  `uncertain`.
- Let suitable HA actions await a bounded terminal result.
- Expose the last command result through a stable diagnostic entity or event so
  automations can wait for confirmation without interpreting optimistic state
  as reported charger state.
- Do not leave unresolved futures behind during reload or deduplication.

**Acceptance tests:**

- Every completed, replaced, expired, and cancelled queue item resolves once.
- Integration unload resolves or cancels every waiter.
- An automation can distinguish enqueueing from charger confirmation.

## Proposed commit sequence

1. `docs: add automation resilience roadmap`
2. `fix(ha): reject blocked automation actions`
3. `fix(writes): isolate superseded automation intents`
4. `fix(writes): expire and revalidate queued commands`
5. `fix(ocpp): harden transaction and charger identity guards`
6. `fix(schedules): coalesce paired and compound updates`
7. `fix(services): coalesce refresh and validate inputs`
8. `feat(diagnostics): expose charger command outcomes`
9. `chore(release): prepare 1.7.0-dev.29`

Each behavioural commit should include its focused regression tests and inline
comments for timing, safety, or reconnect rules that are not obvious from the
code alone.
