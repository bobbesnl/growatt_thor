# Native charging targets

## Scope

The Growatt THOR exposes vendor-specific duration, energy, and budget targets
through OCPP `DataTransfer`. The observations below were made on
`THOR_22AS-V2.2.16-20240902` in Fast mode. They are firmware-specific evidence,
not a general OCPP capability claim.

The integration reproduces observed command sequences and preserves uncertain
outcomes. It never adds a Home Assistant stop timer or treats an accepted
command as proof that the physical target was reached.

## Evidence matrix

| Target and start | Observed charger-facing sequence | Result | Confidence |
| --- | --- | --- | --- |
| Energy, immediate | `G_SetEnergy(1)` + `RemoteStartTransaction` | THOR stopped locally at exactly 1000 Wh; a later cloud stop was rejected | Native energy stop verified for the tested flow |
| Energy, one-time | target + `ReserveNow`; at due time target refresh + remote start | THOR entered Reserved, started at the boundary, and stopped at 1000 Wh | Sequence and native stop verified |
| Duration, immediate | `G_SetTime(60)` + remote start | Command sequence accepted in the original capture | Sequence verified; completion not observed in that capture |
| Duration, daily | no command when saved; target + remote start at due time | THOR stopped after approximately five minutes | Due-time sequence and native duration stop verified |
| Budget, immediate | `G_SetAmount` + remote start | `0,10` ended at 0 Wh; `1` charged normally but was stopped manually | Wire format observed; monetary enforcement unverified |
| Budget, one-time | `G_SetAmount(49,99)` + `ReserveNow` | Commands accepted | Reservation sequence observed; completion unverified |
| Daily schedules | no charger-side schedule persisted when saved | cloud issued target + remote start at the selected time | One occurrence observed; recurrence remains HA-owned |

Growatt includes an extra `connectorId=1` in its vendor `DataTransfer`, outside
the standard OCPP 1.6 schema. Only the narrow target adapter bypasses schema
validation for this captured extension. Budget values use a decimal comma and
carry no currency.

OCPP defines `ReserveNow.expiryDate` as the reservation expiry. Growatt used a
timezone-naive value matching the selected local start boundary and sent the
remote start at that time. This behavior must not be generalized to other
chargers.

## Integration contract

- **Immediate:** send the native target and either start remotely or wait for
  Plug & Charge/RFID according to the reported authorization mode.
- **One-time:** persist intent, send target + `ReserveNow`, refresh the target at
  the boundary, and then remote-start. Missed or uncertain requests are never
  replayed automatically.
- **Daily:** Home Assistant retains local wall-clock recurrence and sends target
  + remote start when due. No recurring schedule is claimed on the charger.
- **Cancellation:** daily schedules are removed locally; accepted one-time
  reservations use their exact ID with `CancelReservation`. A native target
  already written to the THOR is not implicitly cleared.
- **Replacement:** terminal requests require an explicit matching request ID.
  In-flight and unknown outcomes require manual reconciliation.

Every mutating path rechecks firmware, working mode, connection identity,
charger fault, active transaction, authorization mode, and queue state. Intent
is stored before transmission. Transport failures remain unknown rather than
being reported as rejected.

## Guardrails and open questions

- Supported evaluation bounds are 1–1440 whole minutes, 0.01–100 kWh, and
  1–1000 charger-tariff units. These are software guardrails, not validated
  hardware limits.
- Budget remains explicitly experimental until native completion, currency,
  minimum, and precision rules are established.
- Successful clearing and target lifetime across stop, unplug, reconnect, and
  reboot remain unverified.
- Only one recurring due event was captured; timezone and DST handling are an
  explicit Home Assistant responsibility.
- Other firmware and hardware generations require independent validation.

Raw captures contain network metadata and identifiers and remain private. The
public test fixtures retain only redacted command fields and expected state
transitions.
