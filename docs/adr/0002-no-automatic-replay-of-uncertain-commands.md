# 0002. Never replay a command whose outcome is uncertain

Status: Accepted

## Context

A connection can drop after a request was sent but before the charger answered.
The charger may then have applied the command, partly applied it (PV Linkage
Apply has several steps) or never received it. Repeating it automatically could
start a second transaction, revert a newer user intent or apply a compound
change twice.

## Decision

A request that may have reached the charger ends with the result `uncertain`.
The queue does not resend it on the next connection. Requests that were
definitely not sent may wait for a reconnect, subject to their policy and
lifetime. Where a readback exists, the integration reconciles with the charger
instead of guessing: configuration writes schedule a `GetConfiguration`
readback, and transaction state comes from `StartTransaction` /
`StopTransaction`.

## Consequences

- Automations see `uncertain` and decide themselves whether to retry.
- An uncertain Remote Start keeps its short-lived authorization grant so that a
  resulting `StartTransaction` is not denied.
- PV Linkage Apply reports partial progress instead of restarting from the
  beginning.
- Enforced by the [invariants](../invariants.md#commands-and-transactions) and
  the queue tests. Background:
  [automation resilience](../automation-resilience.md#9-expose-the-actual-outcome-of-a-command).
