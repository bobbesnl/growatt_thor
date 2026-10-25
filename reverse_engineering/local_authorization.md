# Local OCPP authorization

## Evidence boundary

On the tested `THOR_22AS-V2.2.16-20240902` firmware, APP mode
(`G_ChargerMode=1`) sent OCPP `Authorize` requests to the connected central
system. During the same investigation, the tested card swipe in RFID-only mode
did not produce `Authorize` or `StartTransaction` traffic. The printed card
number, the transmitted identifier, card provisioning, and behavior on other
firmware must therefore not be assumed to be equivalent.

These observations justify controlling responses to inbound OCPP authorization
requests. They do not prove that an `Invalid` response physically prevents every
firmware and mode from charging.

## Integration behavior

Local authorization is disabled by default, preserving existing installations.
When enabled, an exact-match allowlist is evaluated independently for each
inbound `Authorize` and RFID-originated `StartTransaction` request. An enabled,
empty allowlist rejects every card. Policy changes affect only later requests
and never stop an active transaction.

Starts initiated by Home Assistant use a separate permission. An accepted
remote-start command creates a short-lived, one-shot grant for the matching
`StartTransaction`; its technical OCPP identifier is not added to the RFID
allowlist. Plug & Charge remains governed by the explicit charger mode rather
than being treated as a physical card.

Denied starts still receive a transaction identifier so later meter and stop
messages can be correlated. Stops are always processed.

## Storage and privacy

The settings offer an explicit, two-minute learning window for the next valid `Authorize` identifier on the selected entry's current connection. Capturing it does not change the authorization response. The user must confirm before it is added to the allowlist; rejected cards can therefore be learned without granting temporary access. Other entries, superseded connections, technical `StartTransaction` identifiers and swipes before the window are not used. The temporary identifier is cleared on expiry or successful confirmation and is never persisted as learning state.

Optional aliases are stored separately from the exact-match identifiers. Existing identifier-only lists remain valid. The editable list uses `identifier | alias` with a spaced separator; bare pipes within an identifier remain literal. Authorization never matches aliases. Session start captures the alias as metadata, and active-session and pending-completion checkpoints preserve it until CSV delivery. The CSV columns `authorized_identifier` and `authorized_alias` remain blank when no matching start metadata exists; historical names are not reconstructed from the current allowlist.

The editable allowlist is stored in the Home Assistant config entry and is
therefore present in Home Assistant backups. Identifiers are omitted from normal
integration logs and downloaded diagnostics. Raw WebSocket logging and packet
captures can still expose them and require separate protection.

Aliases follow the same log and diagnostic redaction rules as identifiers. Identifiers and aliases are intentionally included in retained session CSV files and CSV downloads, which must be treated as private. Learning does not add raw payload or identifier logging.

Diagnostics expose only policy validity, the number of configured identifiers,
the Home Assistant start permission, and bounded decision metadata.

## Remaining validation

- Verify accepted and rejected cards on each supported firmware and charger
  mode.
- Confirm physical charging behavior following a rejected `StartTransaction`.
- Check reconnect, cache, repeated-swipe, and offline behavior.
- Verify that changing policy between `Authorize` and `StartTransaction`
  remains fail-closed.

Private packet captures and RFID tooling are deliberately not part of the
repository. Tests exercise the real Python OCPP routing and response schemas
without retaining card identifiers in fixtures or diagnostics.
