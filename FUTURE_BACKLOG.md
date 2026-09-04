# Future backlog

Status: proposals for discussion, not a release commitment.
Baseline: `development`, `1.7.0-dev.26`, reviewed on 2026-09-04.

This backlog records ideas from a comparison with evcc. The integration should
provide reliable local THOR control, understandable feedback, and useful Home
Assistant automation interfaces. House-wide energy optimisation can build on
those interfaces.

Existing capabilities include native charging strategies, External Meter
controls, PV/Boost settings, charging periods, configuration readback tracking,
session records and exports, fault diagnostics, and model-specific current
limits. The items below extend that foundation; they are not all missing features.

## Design decisions

- Prefer the wallbox's native functions for one-time charging targets and the
  existing implemented/adapted Scheduled variants. Do not introduce a duplicate
  HA timer or energy-counter controller for those targets.
- Keep native one-shot targets, persistent charging windows, reservations, and
  app/cloud schedules distinct. A similar UI label does not establish identical
  protocol behaviour or persistence.
- Separate requested settings, accepted commands, confirmed device state, and
  actual energy transfer.
- Keep capture evidence, hypotheses, and ATESS comparison documentation distinct.
  Implement new writes only after their behaviour has been confirmed.
- Retain firmware protections and existing reverse-engineering documentation.

## Functional requirements

### F01 — Track commands through to their observed effect

Priority: high; suggested first development package.

- Show queued, sent, accepted, confirmed, rejected, timed-out, or superseded
  outcomes as appropriate for the operation.
- Distinguish an accepted start request from a started transaction and actual
  energy transfer. Confirm stopping independently as well.
- Give users and automations a useful result when the expected effect does not
  occur. Account for legitimate waiting states.
- Extend existing configuration readback handling where appropriate.

Acceptance example: `RemoteStartTransaction` returning `Accepted` without a
subsequent transaction must not be reported as a completed charging start.
Growatt Forced Start/Stop remains a separate capture investigation.

### F02 — Explain why charging is waiting or unavailable

Priority: high.

- Expose understandable reasons such as a reported charger fault, an applicable
  time window, missing authorisation, or a vehicle-reported pause where supported
  by evidence.
- Distinguish charger-reported facts from derived explanations; retain an
  explicit unknown reason when the available data is insufficient.
- Explain why a control is unavailable and what condition would enable it.

### F03 — Separate installation limits from requested charging current

Priority: high; confirm the appropriate device-side enforcement mechanism.

- Keep model capability, configured installation limit, requested current, and
  confirmed effective setting distinct.
- Reject requests above the installation limit, including automation requests.
- Show the active limiting setting when known. A 32 A model does not imply that
  its installation permits 32 A.
- Document what remains enforced when HA or the connection is unavailable.

### F04 — Provide a defined interface for external charging control

Priority: high; dependent on protocol and firmware validation.

- Provide documented HA actions/entities for charging permission, current
  requests, and observable command outcomes.
- Define ownership and interaction with native PV, Boost, and time programmes
  so that competing controllers do not continually overwrite each other.
- Confirm whether `G_MaxCurrent` is suitable for recurring current regulation,
  or whether another supported mechanism is required. Do not infer this from
  the key name or successful occasional configuration writes.
- Document supported update rates, latency, and behaviour after controller loss.
- Evaluate evcc interoperability through HA after these semantics are confirmed;
  compatibility is not established by this backlog.

### F05 — Improve access to existing native charging targets

Priority: medium; refinement of existing Scheduled/native functionality.

- Reuse wallbox-supported targets and the existing Scheduled variants rather
  than implementing a second HA-side stop controller.
- Review whether target selection, activation, cancellation, and completion are
  understandable and consistently exposed to automations.
- Display target status only to the extent confirmed by device feedback; do not
  present a locally retained request as a confirmed active target.
- Verify target lifetime across unplugging, session completion, reconnects, and
  reboots before promising automatic reset or persistence.

The capture findings distinguish `G_SetTime`, `G_SetEnergy`, `G_SetAmount`,
`ReserveNow`, Smart Boost target data, and recurring app/cloud schedules. This
backlog does not claim all combinations have identical support or semantics.

### F06 — Provide useful automation triggers

Priority: high to medium.

- Expose meaningful transitions for connection to a vehicle where observable,
  actual charging start/end, confirmed target completion, command failure,
  charger fault, and recovery.
- Avoid duplicate events on repeated messages or reconnects.
- Let HA handle notification destinations and user-specific automation policies.

### F07 — Make charging sessions more understandable

Priority: medium.

- Extend existing history with supported end reasons, interruptions, and data
  completeness information.
- Keep charger-reported cost separate from any optional tariff-based estimate.
- Preserve provenance when measurements are incomplete or records arrive late.
- Reuse existing session identities, persistence, and exports.

### F08 — Explicit local RFID authorisation and optional session assignment

Priority: deferred pending a working card and controlled captures.

- Define the intended authorisation policy; the current OCPP Authorize handler
  generally accepts incoming requests and is not a managed card allowlist.
- Consider local card permissions and optional named vehicle/user assignment.
- Keep local authorisation, Growatt cloud binding, and physical card programming
  separate. No RFID write implementation is authorised by this backlog.
- Do not assume ATESS provisioning requirements explain the tested THOR failure.

### F09 — Isolate multiple chargers

Priority: demand-driven.

- Scope connections, queues, entities, and session state to each charger.
- Verify that a reconnect or command for one charger cannot affect another.
- Treat coordinated load distribution as a separate energy-management feature.

## Non-functional requirements

| ID | Requirement | Verification criterion |
| --- | --- | --- |
| N01 | Defined failure behaviour | Document and test HA restart, charger reboot, connection loss, and stale data. Distinguish native functions that continue autonomously from functions requiring HA. |
| N02 | No stale command execution | Invalidate obsolete starts after unplugging or session changes. A queued stop for one transaction must not affect a later transaction. |
| N03 | Firmware-friendly command handling | Bound queue growth, coalesce superseded requests, limit retries, and define stop-request handling within verified firmware constraints. Preserve the current protections until evidence supports changes. |
| N04 | Visible data quality | Distinguish unknown, stale, estimated, and measured values, including real zero readings. Retain timestamps and provenance for critical data. |
| N05 | Device capability awareness | Base controls on confirmed model/firmware capabilities or device responses. Unknown support remains explicit. |
| N06 | Privacy throughout the data path | Protect card identifiers, PINs, and credentials in normal/error logs as well as diagnostics. Review export access and retention, including the current `/local/` download path. |
| N07 | Reliable HA lifecycle and upgrades | Unload tasks and connections cleanly; preserve entity identities, statistics, and sessions through migrations. Bound memory, storage, and log growth. |
| N08 | Scenario-based regression coverage | Test accepted commands without effect, reconnect during charging, delayed/duplicate messages, queue/session races, and HA restart. Use redacted capture-derived fixtures where useful. |
| N09 | Maintainable evidence and compatibility records | Extend existing reverse-engineering documents with source and firmware scope. Keep unit-test results separate from real-device validation. |

## Features better handled above the device integration

- Dynamic-tariff optimisation, PV forecasts, and departure-time/SoC planning:
  provide reliable controls for evcc or HA orchestration. Vehicle SoC requires
  an additional trustworthy source; it is not inferred from delivered energy.
- Home-battery priorities and house-wide load distribution: coordinate at the
  energy-management level with explicit ownership of THOR's native controls.
- Simple user-specific rules and notifications: consider HA blueprint examples.

## Separate investigations

- Forced Start/Stop and charger-side Lock/Unlock Gun: resume controlled captures;
  earlier ambiguous attempts are not sufficient implementation evidence.
- Automatic phase switching: only consider after hardware and firmware support
  are established. A phase configuration setting does not prove switching support.
- OCPP forwarding to a cloud backend: a separate project requiring command
  ownership, transaction mapping, and Growatt-specific compatibility validation.

## Suggested order

1. F01/F02 with N01–N04 and relevant scenario tests: observable command effects,
   waiting reasons, and reliable reconnect/queue behaviour.
2. F03/F04: installation limits and a validated external control interface.
3. F05/F06/F07: native-target usability, automation triggers, and session clarity.
4. Reassess RFID and multiple chargers when evidence and user demand justify them.

## References

Local evidence and implementation baseline:

- [Current release scope](CHANGELOG.md)
- [THOR capture findings](reverse_engineering/thor_22as_capture_findings.md)
- [Hardware and firmware variants](reverse_engineering/hardware_firmware_variants.md)

evcc comparison sources, consulted on 2026-09-04; these describe evcc, not
confirmed THOR capabilities:

- [Feature overview](https://docs.evcc.io/en/)
- [Home Assistant integration](https://docs.evcc.io/en/smarthome/home-assistant/)
- [Minimum charge and limits](https://docs.evcc.io/en/features/limits/)
- [Solar surplus charging](https://docs.evcc.io/en/features/solar-charging/)
- [Load management](https://docs.evcc.io/en/features/loadmanagement/)
- [OCPP forwarding](https://docs.evcc.io/en/integrations/ocpp-forwarding/)
