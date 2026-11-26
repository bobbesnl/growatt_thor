# 0004. Use UTC for application timestamps and keep device values as reported

Status: Accepted

## Context

The THOR reports some times in device-local time, sometimes without an offset.
HA, the browser and the charger can be in different time zones, and daylight
saving time creates missing and repeated local times. Existing CSV rows, session
identities and deduplication keys were built from the original values.

## Decision

Timestamps the integration sends to cards, the session-detail WebSocket and CSV
exports are UTC ISO strings with `Z`. The frontend formats them in HA's
configured installation time zone. Growatt wire values, raw diagnostics and stored
source CSV times keep their reported form. UTC is computed after session identity
and correlation. Naive local times are interpreted in the installation zone; a
missing or ambiguous instant is shown as unknown instead of guessing an offset.

## Consequences

- Existing rows, deduplication keys and session IDs are never rewritten.
- Time parsing lives in `timestamps.py` with explicit options for the few legacy
  differences between callers.
- Daily target schedules keep a local clock time plus zone; reservation requests
  are encoded in device-local time only at the wire boundary.
- Details: [time boundaries](../architecture.md#time-boundaries).
