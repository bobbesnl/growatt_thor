# 0006. Deliver completed sessions through a checkpointed outbox

Status: Accepted

## Context

A completed session is assembled from the OCPP transaction and a later Growatt
session record, then written to the CSV history. HA can restart or crash at any
point, and the CSV write runs in an executor. Losing a completed session or
counting it twice would corrupt history and energy totals.

## Decision

Completed rows are placed in `SessionOutbox`. Before appending, the outbox saves
the HA storage checkpoint with the row still pending; after a successful append
it removes the row and saves again. A failed append keeps the row for a retry at
setup, after later completions and at shutdown. Each row carries a session ID so
that a repeated append is ignored. History writes are serialized by one lock and
protected by a recovery journal that replays the resulting rows, not the
additions.

## Consequences

- At-least-once delivery with deduplication by session ID; a bounded set of
  1,000 recent delivery identities protects against recent retries, not against
  replaying an unlimited old stream.
- Backups must include HA storage, the CSV, the archive summary and any pending
  journal together.
- Details: [persistent completion](../architecture.md#persistent-completion).
