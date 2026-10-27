# Everyday charging

[Handbook](../README.md#documentation) · [Installation](installation.md) · [Charging](usage.md) · [Energy](energy.md) · [Sessions](sessions.md)

Start here after [installing the integration](installation.md). Add the bundled
card through **Edit dashboard → Add card → Growatt THOR**. After updating,
restart Home Assistant and refresh the browser; no separate frontend package or
manual JavaScript resource is needed. With one THOR status sensor, the card
finds the integration automatically. Use the visual editor to select a specific
installation, name, theme, gauge ceiling and optional sections.

```yaml
type: custom:growatt-thor-card
name: Garage
max_power: 22
```

- [Read and operate the charging card](#charging-card)
- [Choose how charging is authorized](#local-charging-authorization)
- [Set an energy, duration or budget target](#native-charging-targets)
- [Configure PV charging and energy sources](energy.md)
- [Review sessions and export data](sessions.md)

## Read the charging card

The red numbers match the explanations below each image. Screenshots use
illustrative values; [all original images and capture details](screenshots.md)
are available separately.

<a id="charging-card"></a>

<a href="images/annotated/charging-card.png"><img src="images/annotated/charging-card.png" alt="Charging card with numbered annotations" width="580"></a>

1. **Charging and authorization modes.** Open the badges to review or change charging strategy and how a session is authorized.
2. **Status and grid balance.** The left label is the charger state. The right badge describes site grid import or export, not total charging power.
3. **Power and charging sources.** The gauge shows EV charging power. Green, purple and amber indicate direct PV, battery and grid contributions. The blue marker indicates the control target; battery origin remains unknown.
4. **Phase currents.** See active phases and current per phase, alongside the configured maximum.
5. **Current session.** Energy added and elapsed session duration. A vehicle pause does not necessarily end the transaction.
6. **Charging controls.** Available controls depend on the authorization mode and charger state. Stop charging requests an OCPP stop.
7. **Charging target.** Open the target dialog for an energy, duration or budget target and its start schedule.

A queued or accepted command is not yet a confirmed physical state. Wait for
the card to report the outcome before issuing another command. During a
vehicle or wallbox pause, the transaction can remain open; see
[pause states](sessions.md#vehicle-and-wallbox-pauses). Missing readings stay
unknown instead of being displayed as zero.

With **Plug & charge**, a connected vehicle can also be started manually after
a completed stop, including an energy-protection stop. The card enables
**Start charging** once the previous transaction has ended and the charger is
ready. The command requests a new session without changing PV Linkage, boost
settings or current limits; it does not guarantee immediate power delivery.
**Stop charging** stays disabled while there is no active transaction.
RFID-only mode continues to require a physical card. Active or unresolved
charging targets and an unavailable HA start entity can still block the button;
an old target attempt blocked before it was sent no longer blocks manual Start.

## Local charging authorization

There are two independent settings: the **wallbox authorization mode** decides
how charging starts, while Home Assistant's **local access policy** decides
which RFID and remote-start requests it accepts.

### Choose the wallbox authorization mode

Open the authorization badge on the card (number **1**) and choose
**Home Assistant / RFID**, **RFID only**, or **Plug & charge**. Review the
confirmation: changing mode can reboot the charger, and Plug & Charge can
start charging immediately when a vehicle is connected.

[Compare the three authorization dialogs](screenshots.md#authorization).

### Manage local access

Open **Settings → Devices & Services → Growatt THOR → Configure → Local access control**.
Existing installations remain open until restriction is enabled.

<a id="ha-authorization"></a>

<a href="images/annotated/ha-authorization.png"><img src="images/annotated/ha-authorization.png" alt="Local charging authorisation with numbered annotations" width="580"></a>

1. **Restrict RFID access.** When enabled, only identifiers on the local allowlist are accepted. An enabled empty list rejects every physical card.
2. **Allow Home Assistant starts.** A separate permission for starts through HA controls, services and automations. Their technical identifiers need not be added to the RFID list.
3. **RFID allowlist.** Enter one exact identifier per line, optionally with a name: `00Ab12 | Family car`. Keep leading zeroes and letter case. These are sensitive access identifiers; the screenshot intentionally contains none.
4. **Submit.** Saves the local policy. This does not change the wallbox’s authorization mode or cloud bindings and does not stop an active session.

An explicitly enabled HA start permission also works when an older installation
still has an obsolete RFID list. That list remains unchanged; physical cards
remain blocked until a valid allowlist is saved.

The editable allowlist is stored in the integration's configuration and included
in Home Assistant backups. Identifiers are omitted from normal logs and
downloaded diagnostics. See the [authorization evidence and limits](../reverse_engineering/local_authorization.md)
for firmware-specific details.

### Learn and name an RFID card

Open **Settings → Devices & Services → Growatt THOR → Configure → Learn RFID card** for the wallbox you want to use. The wallbox must be connected to Home Assistant.

1. Present the card at that wallbox within two minutes, then select **Submit** in the dialog. Only the next card reported by that wallbox is captured. If none has arrived, the dialog lets you try again within the same two-minute window.
2. Check the detected identifier and optionally enter a card name, such as **Family car**. Select **Submit** again to add it to the local allowlist. Closing the dialog without saving adds nothing; the temporary capture is cleared after two minutes.
3. Present the card again to use it with the updated allowlist. Learning does not change the access-control switches. If RFID restriction is enabled, an unlisted card remains rejected until you save it. If access is unrestricted, learning does not prevent the card from starting a session.

The wallbox must send the presented card to Home Assistant. Use **Home Assistant / RFID** mode if **RFID only** does not report it; the integration does not switch modes automatically.

To edit or remove names later, open **Local access control**. A line may contain just the identifier or `identifier | name`, with a space on each side of `|`. Names may contain up to 80 characters. Leave just the identifier to remove its name, or delete the whole line to remove the card. The list accepts up to 100 cards and can also be edited while the wallbox is offline.

Use a name that helps you recognize the card's sessions. For example, keep one card for a particular vehicle and call it **Family car**, or give family members their own cards named **Alex** and **Sam**. The name follows the card used to start charging; it does not automatically identify the vehicle or the person holding it. If you always use the same card for one vehicle, its sessions can be identified by that name in the CSV file.

Names are labels, not access codes; authorization still checks the exact identifier. Names and identifiers are stored locally and included in Home Assistant backups and session CSV files. They remain hidden in normal logs and downloaded diagnostics. See [RFID information in session files](sessions.md#rfid-information-in-session-files) for how names are recorded.

### Use other RFID cards and fobs

You can also use compatible NFC/RFID cards and key fobs instead of the supplied Growatt cards. Other cards and fobs were successfully used in our RFID testing. Compatibility depends on what the wallbox's reader supports; an NFC/RFID label alone does not mean that every card or fob will work. Present it in **Home Assistant / RFID** mode and use **Learn RFID card** to check whether Home Assistant receives its identifier, then save and test it with the intended access settings.

For local access control, the card or fob supplies an identifier that Home Assistant checks against the allowlist. This use does not require the Growatt card's balance/credit features. Those Growatt-specific features are not provided for other cards or fobs by learning their identifier, and a card name does not add a balance or billing account.

## Native charging targets

Open **Charging target** on the card (number **7**). Choose what to limit, then
when to start:

| Target | Unit | Meaning |
| --- | --- | --- |
| Energy | kWh | Energy to add in this charging session |
| Duration | minutes | Requested charging duration |
| Budget | displayed currency | Experimental native cost limit |

**Now** sends the target immediately. **At a set time** offers either a one-time
reservation or **Every day**, a schedule stored and run by Home Assistant.
A scheduled start is not a finish-by deadline; [PV Smart Boost](energy.md#pv-charging-dialog)
is a separate feature. Starts depend on authorization mode, vehicle readiness
and the charger. The dialog explains prerequisites and reports acceptance or
uncertainty.

Energy and duration enforcement have been verified only on the documented
THOR 22AS firmware. Budget stopping and currency semantics remain experimental.
Unresolved target requests block ordinary starts until reconciled; requests
are retained across restarts and are not retried automatically. See
[charging-target evidence and limits](../reverse_engineering/charging_targets.md)
when using the corresponding HA actions.

### Charging target dialogs

The three examples below explain the shared controls. The [screenshot index](screenshots.md#charging-targets)
contains all nine combinations of target type and start schedule.

#### Add energy now

<a id="target-energy"></a>

<a href="images/annotated/target-energy.png"><img src="images/annotated/target-energy.png" alt="Energy target — now with numbered annotations" width="580"></a>

1. **Target type.** Choose energy, duration or budget. Each has its own unit and limits.
2. **Energy to add.** Requested energy in kWh. This is an energy target for the session, not a vehicle battery percentage.
3. **Start now.** The target is sent now. Actual charging starts according to authorization mode, vehicle readiness and the supported charger behavior.
4. **Selection preview.** Review the amount and start behavior before sending the request.
5. **Confirmation and action.** Read the status, confirm the request and use “Set charging target”. A submitted request is not itself proof of charger acceptance.

#### Reserve a one-time duration target

<a id="target-duration"></a>

<a href="images/annotated/target-duration.png"><img src="images/annotated/target-duration.png" alt="Duration target — scheduled once with numbered annotations" width="580"></a>

1. **Duration target.** Choose Duration for a time-based charging target.
2. **Charging duration.** Enter the requested duration in minutes. This differs from choosing when charging should start.
3. **At a set time.** Switch from immediate to scheduled start.
4. **Start date and time.** The scheduled start is in the device’s local time. It is a start time, not a finish-by deadline.
5. **Every day unchecked.** Leave this unchecked for a one-time reservation. Enable it for a daily start instead.
6. **Review the reservation.** Check target duration and the scheduled date and time.
7. **Confirm and reserve.** Read the current status and confirmation before “Reserve once”. One-time reservations are experimental and subject to the readiness requirements in the usage guide.

#### Schedule a daily budget target

<a id="target-budget"></a>

<a href="images/annotated/target-budget.png"><img src="images/annotated/target-budget.png" alt="Budget target — every day with numbered annotations" width="580"></a>

1. **Budget target.** Choose Budget for a cost-based native charging target.
2. **Cost limit.** Enter the budget in the displayed currency. The Home Assistant display currency and charger tariff must match operationally.
3. **Scheduled start.** Select “At a set time” and choose the local start date and time.
4. **Every day enabled.** Repeat at the selected local clock time. Home Assistant stores and runs this daily schedule.
5. **Selection preview.** Check the budget, time and daily recurrence before scheduling.
6. **Experimental behavior and confirmation.** Automatic stopping at the budget is not fully verified. Read the warning and confirmation before “Schedule daily”. This is separate from PV Smart Boost.

## More controls and troubleshooting

Use the [entity and automation reference](entities.md) for maximum-current
controls, reported configuration values, diagnostics and YAML examples.
For unavailable readings, delayed commands or firmware limitations, follow
[troubleshooting](troubleshooting.md).


### Connection loss

The status sensor stays available with state `offline` when the OCPP connection
is lost. Both cards retain their data and session history; controls remain
blocked until the wallbox reconnects. Before the first charger status arrives,
the connected status sensor can be `unknown` while still carrying the card data.
Automations monitoring connection loss should test for `offline` (and may also
handle `unavailable` during integration unload or HA shutdown).

The card contract uses additional entity attributes. Home Assistant only includes
these attributes for available entities, as implemented in the
[HA state calculation](https://github.com/home-assistant/core/blob/2026.10.4/homeassistant/helpers/entity.py#L1032-L1038).

### Charging, but waiting for current measurements

The wallbox can report **Charging** while the card shows **No data** and **Waiting for current readings**. Charging status and current measurements arrive separately. Check whether the ordinary charging-power and phase sensors still update, then compare the meter sample time with its receipt time in the integration diagnostics.

After a clock change, some wallboxes retain a fixed offset such as UTC+2 while Home Assistant's local time has moved to UTC+1. The integration uses the wallbox's reported fixed offset for live meter timestamps when its daylight-saving setting is known to be disabled. Otherwise it retains Home Assistant's time zone. It does not change the wallbox clock or make old samples current by substituting their receipt time. The technical [clock observation](../reverse_engineering/thor_22as_capture_findings.md#fixed-wallbox-clock-after-the-autumn-change) records the confirmed firmware behavior.


Target start times are entered in Home Assistant's configured time zone, shown
beside the field. The browser's time zone does not change the selected start.
A skipped or repeated local time at a DST transition is rejected by the dialog;
choose an unambiguous time, or use a service with an explicit UTC offset. Daily
recurrence keeps the requested installation-local clock rather than a fixed UTC
hour. Device-native reservation times are converted by the integration.
