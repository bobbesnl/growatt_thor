# How EV energy and costs are calculated

This reference explains how the 2.0 integration divides charging energy between
solar, grid and battery, and what the results can tell you. For setup, sensor
selection and tariffs, use the [Energy handbook](energy.md).

## Start with the energy measured by the wallbox

The wallbox's energy counter provides the total. Each time it increases, the
integration uses the available site readings to divide that energy between
sources. Power sensors in W, kW and MW are converted to the same unit before
calculation. Grid import and battery discharge are treated as positive values.

The result uses four categories:

| Source | Meaning |
| --- | --- |
| Direct solar | Solar energy assigned directly to EV charging. This is the only source counted as green energy. |
| Direct grid | Energy assigned to grid import. Its cost uses the electricity price for that interval. |
| Battery | Energy assigned to battery discharge. The integration does not know whether it originally came from solar or the grid. |
| Unknown | Energy that cannot be assigned with the available data. It still counts towards the session total. |

For example, a session with **10 kWh** might contain **6 kWh solar**, **2 kWh
grid**, **1 kWh battery** and **1 kWh unknown**. Its source coverage is **90%**:
9 of the 10 kWh could be assigned. Coverage describes how much energy has an
assignment, not how accurate the sensors are. The green-energy total is shown
only when the whole session has valid source coverage.

## How the energy is divided

Site sensors usually measure the whole home, so their readings do not prove
which source supplied the car. The integration therefore applies a stated
allocation rule:

- **Grid without PV:** assigns EV energy to the grid, based on the selected site profile.
- **Default rule for PV profiles:** assigns measured grid import to the EV first, then battery discharge, then available solar. Any remainder stays unknown.
- **GroHome Load First:** reserves solar for household use and battery charging before assigning the remaining solar to the EV. Grid and battery readings help account for the rest.

Load First is an assumption used in the calculation. Selecting it does not
change priorities or settings on the inverter, battery or other devices.
The current integration supports one active wallbox.

## What happens when data is missing

Missing, stale or invalid readings can leave part of the energy unassigned.
The integration keeps that part **unknown** instead of treating it as zero or
applying today's source mix to an earlier gap. Older sessions are not filled
in retrospectively.

After a restart, saved session data allows accounting to continue. If a saved
meter reading has no usable timestamp, the integration starts a new comparison
point; it does not guess how energy was supplied during the gap. At session
completion, the source totals are reconciled with the reported session energy
and added to the cumulative site sensors.

The charging card shows the **current power mix**; the session card shows
**energy accumulated over time**. These can differ. A live energy value marked
with `≈` is an estimate from power readings, separate from the counter-based
accounting.

## What the cost means

**Effective grid cost** is the assigned grid energy multiplied by the price
valid for each interval. For example, 2 kWh at EUR 0.30/kWh costs EUR 0.60.
Negative prices are supported. This calculation is separate from the session
cost reported by the wallbox; it does not price battery use or lost solar
export income.

A price sensor must provide a usable value in the configured Home Assistant
currency. An unchanged price does not expire simply because its update time
is old; any declared validity period still applies. A newly observed price is
not used to recalculate earlier energy. Missing prices remain unknown, not
confirmed zero cost. See [Choose the tariff](energy.md#choose-the-tariff) for
supported units and sensor behavior.

## Automatic stopping is a separate option

Accounting records energy and costs. An optional rule can also stop charging
when grid import or battery discharge persists. It must be enabled explicitly
and does not restart charging or control the home battery. The conditions and
thresholds are described under [Automatic charging stop](energy.md#automatic-charging-stop).

## Current limits

The integration does not yet provide:

- Tracking of the original solar or grid energy stored in the home battery, or its storage losses.
- Persistent monthly and yearly summaries, or the value of solar energy that could have been exported.
- Separate allocations for multiple wallboxes, vehicles or people.
- Whole-home power optimization or control of batteries and GroBoost.
- Complete historical curves for current limits, solar, household and battery power. The backend currently stores charging power and session events; additional simulator curves are examples.

Results depend on sensor placement, measurement quality and wallbox firmware.
For backup guidance, see [Session history](sessions.md). For implementation and
recovery details, see [Persistent completion](architecture.md#persistent-completion).
