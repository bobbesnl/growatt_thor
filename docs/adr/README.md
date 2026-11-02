# Architecture decision records

[Documentation](../../README.md#documentation) · [Architecture](../architecture.md) · [Invariants](../invariants.md)

A decision record explains why a rule exists, so that it can be changed on
purpose rather than by accident. Each record describes the situation, the
decision and its consequences. Rules that follow from these decisions are listed
in the [invariants](../invariants.md).

| Record | Decision | Status |
| --- | --- | --- |
| [0001](0001-single-charger-write-owner.md) | One write queue per charger owns all outbound charger writes | Accepted |
| [0002](0002-no-automatic-replay-of-uncertain-commands.md) | Commands with an uncertain outcome are never replayed automatically | Accepted |
| [0003](0003-native-charging-targets.md) | Charging targets use the wallbox's native limits; only daily repeats run in HA | Accepted |
| [0004](0004-utc-at-presentation-boundary.md) | Application timestamps are UTC; device and stored values keep their original form | Accepted |
| [0005](0005-rfid-safe-logging.md) | Authorization and transaction paths log without RFID payloads | Accepted |
| [0006](0006-checkpointed-session-outbox.md) | Completed sessions reach CSV through a checkpointed outbox | Accepted |

These records were written down in 2026-11 for decisions already in effect in
the 2.0 line. Their history is in [automation resilience](../automation-resilience.md),
the [backlog design decisions](../backlog.md#design-decisions) and the git log.

## Adding a record

Copy the structure below into `NNNN-short-title.md` with the next free number and
add it to the table. Superseded records stay in place with status
`Superseded by NNNN`.

```markdown
# NNNN. Title in the imperative

Status: Proposed | Accepted | Superseded by NNNN

## Context
What problem or constraint makes a decision necessary?

## Decision
What we do, stated so that a reviewer can check code against it.

## Consequences
What becomes easier, what becomes harder, which rules and tests enforce it.
```
