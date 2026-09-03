# THOR Hardware and Firmware Variants

The Growatt THOR product family is not a single hardware and firmware target.
Community reports and manual illustrations show different enclosure and PCB
layouts, while firmware availability and OCPP behavior vary between devices.
Model, hardware generation, and firmware version must therefore be tracked
separately.

## Known combinations

| Source | Charger | Hardware evidence | Firmware | Relevant behavior |
|---|---|---|---|---|
| Contributor capture device and May 2022 German manual | THOR 22AS-S/P, three-phase | 295 x 466 x 189 mm enclosure, red emergency stop, separate forced start/stop button, and older side-window connection PCB | `THOR_22AS-V2.2.16-20240902` | Primary reverse-engineering target; no newer firmware is currently offered to this device in ShinePhone |
| [April 2023 THOR 11/22AS guide](https://growatt.tech/wp-content/uploads/shared-files/THOR-11kW22kW-AC-EV-Charger-User-Manual-202304.pdf) | THOR 11/22AS-S-V1 | 240 x 380 x 164 mm enclosure and a different side-window PCB with a large relay | Not stated | Separate reset/control and connection/power PCBs are shown, but neither has a public revision identifier |
| [Discussion #20](https://github.com/bobbesnl/growatt_thor/discussions/20) | THOR 22AS, three-phase 22 kW | Not stated | `THOR_22AS-V5.2.12-20250310` | ShinePhone worked, but `12345678` was rejected by both the local web interface and Wi-Fi access point |
| [Discussion #38](https://github.com/bobbesnl/growatt_thor/discussions/38) | THOR-07AS-S, single-phase | Not stated | Updated from `V4.2.13` to `THOR_07AS-V4.2.15-20251009-remote` | EU ShinePhone update; phase metadata and status behavior changed |
| [Discussion #14](https://github.com/bobbesnl/growatt_thor/discussions/14) | THOR-07AS-P, single-phase | Not stated | Updated from `THOR_07AS-V6.2.8-20230310` to `THOR_07AS-V6.2.13-20250206` | Unfiltered `GetConfiguration` produced an oversized or malformed response; targeted key requests worked |

The higher V4, V5, and V6 version numbers do not establish an upgrade path
from the THOR 22AS V2 firmware. The available evidence does not show whether a
firmware branch is selected by charger model, hardware generation, region,
release channel, or a combination of these factors.

## Documented hardware layouts

| Characteristic | May 2022 layout | April 2023 layout |
|---|---|---|
| Model wording | THOR 11AS-S/P and 22AS-S/P | THOR 11/22AS-S-V1 |
| Enclosure dimensions | 295 x 466 x 189 mm | 240 x 380 x 164 mm |
| Exterior controls | Red emergency stop and separate forced start/stop button | Smaller enclosure without the red emergency stop in the product image |
| Side-window PCB | Approximately square board with AC, CT/meter, eSense, and SIM connections | Different integrated connection/power board with a large relay and rearranged terminals |
| Reset/control PCB | Not shown | Separate elongated control PCB shown in the troubleshooting section |

These descriptions distinguish manual editions and visible layouts; they are
not manufacturer-assigned hardware revision names. The `V1` suffix in the
April 2023 model wording is likewise not a firmware or PCB revision.

The May 2022 source is a contributor-supplied German reseller manual and is
not distributed with this repository.

The separate reset/control and connection/power PCBs shown in the April 2023
guide belong to the same charger design and must not be counted as two charger
revisions. No reliable hardware-revision field is currently known in
`BootNotification`, `GetConfiguration`, or the local web interface.

## Firmware behavior differences

Discussion #38 reports these changes after updating a THOR-07AS-S to
`THOR_07AS-V4.2.15-20251009-remote`:

- `MeterValues` include explicit phase metadata such as `"phase":"L1"`.
- Energy samples include `"context":"Transaction.Begin"`.
- The charger moves from `Finishing` to `Idle` after approximately five
  seconds.
- Revised temperature handling avoids the reported false PE fault at elevated
  internal temperature.

Discussion #14 shows a different compatibility boundary. That THOR-07AS-P
returned more configuration keys than its firmware could encode as one valid
OCPP response. The integration remains compatible by requesting explicit,
bounded key groups instead of relying on an unfiltered `GetConfiguration`.

These behaviors are firmware-specific, not universal THOR guarantees. Parsers
must continue to accept missing `phase` and `context` fields, different status
timing, and partial configuration responses.

## Local access and credentials

The older THOR documentation uses `12345678` for the charger Wi-Fi access
point, and the local web interface calls its credential the Authentication
Key. Do not assume that one value applies to every access method or firmware.
Discussion #20 reports a V5 device on which `12345678` was rejected by both
the port 8080 login and the access point.

Use the access method and credentials configured for the individual charger.
A factory reset is hardware-dependent and should only be performed using the
manual for the exact charger layout.

## Supply and vehicle phases

[Discussion #40](https://github.com/bobbesnl/growatt_thor/discussions/40)
distinguishes the grid supply from the connected vehicle: a THOR 22 can charge
a single-phase EV, but the reported charger requires a three-phase grid
connection. Both `G_PhaseWringMethod` and the corrected spelling
`G_PhaseWiringMethod` returned `NotSupported` in that report. These keys must
not be exposed as a phase-switching control without new device-specific wire
evidence.

## Integration requirements

1. Preserve the OCPP model and firmware strings exactly as reported by
   `BootNotification`.
2. Do not infer a hardware revision from the firmware major version.
3. Keep optional OCPP fields optional while retaining them when present.
4. Keep compatibility fallbacks when newer firmware starts sending more
   complete data.
5. Do not assume fixed status-transition timing across firmware branches.
6. Respect the tested firmware limit of 30 requested configuration keys per
   `GetConfiguration` call.
7. Include model, firmware, and relevant hardware evidence in diagnostics and
   compatibility reports.

The web-interface **Machine Type** field selects a charger model. It is not a
hardware-generation or PCB-revision identifier.

The field is submitted to the charger's local `/config.cgi` endpoint as
`mdtype` and uses the following values:

| `mdtype` | Web-interface model |
|---:|---|
| `0` | `NULL` |
| `1` | `EVA-11S` |
| `2` | `EVA-22S` |
| `3` | `EVA-44S` |
| `4` | `EVA-11S-SE` |
| `5` | `EVA-22S-SE` |
| `6` | `EVA-44S-SE` |

No matching OCPP configuration key is currently known. This local setting is
therefore separate from the `chargePointModel` string reported through
`BootNotification` and is not exposed as a Home Assistant entity.

## Firmware update safety

- Install only firmware offered for the exact device by Growatt or ShinePhone.
- Never install a THOR-07AS package on a THOR 11AS or THOR 22AS.
- Do not cross-flash based on a higher version number.
- Record the full current firmware string and charger settings before an
  official update.
- Do not automate local firmware uploads without a manufacturer-provided
  compatibility identifier and authenticated update source.

## Useful compatibility report

A report for another THOR variant should contain:

- exact `chargePointModel` and redacted serial prefix
- full `firmwareVersion` from `BootNotification`
- single- or three-phase charger model
- enclosure dimensions and visible exterior controls
- connection-board layout or PCB marking, when safely accessible
- region, update source, and version offered by ShinePhone
- redacted `MeterValues`, status transitions, and configuration responses

This information allows behavior to be attributed to a concrete device
combination instead of treating every THOR charger as equivalent.
