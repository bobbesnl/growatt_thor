# 0005. Keep RFID identifiers out of logs and diagnostics

Status: Accepted

## Context

RFID identifiers authorize charging and identify people. HA logs and diagnostics
are often shared in issue reports. OCPP `Authorize`, `StartTransaction` and
`StopTransaction` payloads contain those identifiers, and exception messages can
echo the payload.

## Decision

Authorization and transaction handlers are marked sensitive: their failures are
logged without payload and without exception details. Remote Start failures are
logged without the ID tag. Diagnostics use identifier-free shapes; configuration
values are redacted before logging. Other handlers log exceptions with
tracebacks. Session CSV files and exports do contain identifiers and card names
because users need them; the documentation asks to treat these files as private.

## Consequences

- Some authorization failures are harder to debug from logs alone; diagnostics
  and the command result sensor provide the non-sensitive context.
- New handlers or log lines on these paths must not include `id_tag` values or
  raw payloads.
- Enforced by the [invariants](../invariants.md#ocpp-handlers-and-logging),
  `ocpp_handler_fallbacks.json` and the diagnostics contract.
