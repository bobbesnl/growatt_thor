# Entities and automation reference

[Handbook](../README.md#documentation) · [Installation](installation.md) · [Charging](usage.md) · [Energy](energy.md) · [Sessions](sessions.md)

Use the [charging guide](usage.md) for everyday controls. This reference lists
entity defaults, state semantics and advanced automation examples.

## Entities created

After successful connection, the integration creates the entities below. The listed entity IDs are the defaults generated from the current entity and device names. Existing installations and manually renamed entities may use different IDs.

### Sensors

| Entity name                               | Default entity ID                                                                                                                                                                                                                                                                                                                              | Purpose                                                                                                               |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Status                                    | `sensor.growatt_thor_ev_charger_status`                                                                                                                                                                                                                                                                                                        | Charger status                                                                                                        |
| Last charger fault                        | `sensor.growatt_thor_ev_charger_last_charger_fault`                                                                                                                                                                                                                                                                                            | Most recent actual Faulted event, retained after recovery and enriched with matching Growatt faultmessage details     |
| Charge Point ID                           | `sensor.growatt_thor_ev_charger_charge_point_id`                                                                                                                                                                                                                                                                                               | Connected OCPP charge point ID                                                                                        |
| Charging Power                            | `sensor.growatt_thor_ev_charger_charging_power`                                                                                                                                                                                                                                                                                                | Total charging power (W)                                                                                              |
| Energy Charged                            | `sensor.growatt_thor_ev_charger_energy_charged`                                                                                                                                                                                                                                                                                                | Energy charged in the current session (kWh)                                                                           |
| Total Energy Charged                      | `sensor.growatt_thor_ev_charger_total_energy_charged`                                                                                                                                                                                                                                                                                          | Persistent cumulative charging energy (kWh)                                                                           |
| Current L1/L2/L3                          | `sensor.growatt_thor_ev_charger_current_l1`<br>`sensor.growatt_thor_ev_charger_current_l2`<br>`sensor.growatt_thor_ev_charger_current_l3`                                                                                                                                                                                                      | Charging current per phase (A)                                                                                        |
| Voltage L1/L2/L3                          | `sensor.growatt_thor_ev_charger_voltage_l1`<br>`sensor.growatt_thor_ev_charger_voltage_l2`<br>`sensor.growatt_thor_ev_charger_voltage_l3`                                                                                                                                                                                                      | Charger voltage per phase (V)                                                                                         |
| Power L1/L2/L3                            | `sensor.growatt_thor_ev_charger_power_l1`<br>`sensor.growatt_thor_ev_charger_power_l2`<br>`sensor.growatt_thor_ev_charger_power_l3`                                                                                                                                                                                                            | Charging power per phase (W)                                                                                          |
| Temperature                               | `sensor.growatt_thor_ev_charger_temperature`                                                                                                                                                                                                                                                                                                   | Internal charger temperature (°C)                                                                                     |
| Communication status                      | `sensor.growatt_thor_external_meter_communication_status`                                                                                                                                                                                                                                                                                      | Healthy, Modbus fault, interrupted communication, or not-yet-reported state; includes the retained OCPP fault details |
| Grid power                                | `sensor.growatt_thor_external_meter_grid_power`                                                                                                                                                                                                                                                                                                | External meter power (W)                                                                                              |
| Grid voltage L1/L2/L3                     | `sensor.growatt_thor_external_meter_grid_voltage_l1`<br>`sensor.growatt_thor_external_meter_grid_voltage_l2`<br>`sensor.growatt_thor_external_meter_grid_voltage_l3`                                                                                                                                                                           | External meter voltage per phase (V)                                                                                  |
| Grid current L1/L2/L3                     | `sensor.growatt_thor_external_meter_grid_current_l1`<br>`sensor.growatt_thor_external_meter_grid_current_l2`<br>`sensor.growatt_thor_external_meter_grid_current_l3`                                                                                                                                                                           | External meter current per phase (A)                                                                                  |
| Server URL                                | `sensor.growatt_thor_ev_charger_server_url`                                                                                                                                                                                                                                                                                                    | Configured OCPP endpoint                                                                                              |
| Charger manufacturer/model                | `sensor.growatt_thor_ev_charger_charger_manufacturer`<br>`sensor.growatt_thor_ev_charger_charger_model`                                                                                                                                                                                                                                        | Identity reported in OCPP BootNotification                                                                            |
| Firmware version                          | `sensor.growatt_thor_ev_charger_firmware_version`                                                                                                                                                                                                                                                                                              | Firmware reported in OCPP BootNotification                                                                            |
| Charger serial number                     | `sensor.growatt_thor_ev_charger_charger_serial_number`                                                                                                                                                                                                                                                                                         | Serial number reported in OCPP BootNotification                                                                       |
| Network configuration                     | `sensor.growatt_thor_ev_charger_network_mode`<br>`sensor.growatt_thor_ev_charger_ip_address`<br>`sensor.growatt_thor_ev_charger_subnet_mask`<br>`sensor.growatt_thor_ev_charger_default_gateway`<br>`sensor.growatt_thor_ev_charger_dns_server`<br>`sensor.growatt_thor_ev_charger_mac_address`<br>`sensor.growatt_thor_ev_charger_wi_fi_ssid` | Read-only charger network diagnostics; sensitive values remain redacted in diagnostic downloads                       |
| Working mode                              | `sensor.growatt_thor_ev_charger_working_mode`                                                                                                                                                                                                                                                                                                  | Fast, PV Linkage, or Off-Peak operation                                                                               |
| Authorization mode                        | `sensor.growatt_thor_ev_charger_authorization_mode`                                                                                                                                                                                                                                                                                            | Home Assistant/RFID, RFID only, or Plug & Charge authorization                                                        |
| Reported solar mode                       | `sensor.growatt_thor_ev_charger_solar_mode`                                                                                                                                                                                                                                                                                                    | Disabled, PV Linkage with grid import, or solar-only PV Linkage+ read back from the charger                           |
| Reported PV Linkage grid import allowance | `sensor.growatt_thor_ev_charger_pv_linkage_grid_import_allowance`                                                                                                                                                                                                                                                                              | Charger-normalized grid-import allowance for PV Linkage in kW                                                         |
| PV Linkage boost configuration            | `sensor.growatt_thor_ev_charger_pv_linkage_boost_configuration`                                                                                                                                                                                                                                                                                | Disabled, Manual, or Smart boost mode                                                                                 |
| Solar threshold current                   | `sensor.growatt_thor_ev_charger_solar_threshold_current`                                                                                                                                                                                                                                                                                       | Reported PV threshold current in A                                                                                    |
| Grid off-peak charging                    | `sensor.growatt_thor_ev_charger_grid_off_peak_charging`                                                                                                                                                                                                                                                                                        | Grid off-peak charging flag                                                                                           |
| Off-peak enable setting                   | `sensor.growatt_thor_ev_charger_off_peak_enable_setting`                                                                                                                                                                                                                                                                                       | Normalized off-peak mode state                                                                                        |
| Configured charging periods               | `sensor.growatt_thor_ev_charger_off_peak_schedule`                                                                                                                                                                                                                                                                                             | Shared time windows used for Off-Peak charging or PV Linkage Manual Boost                                             |
| Off-peak current                          | `sensor.growatt_thor_ev_charger_off_peak_current`                                                                                                                                                                                                                                                                                              | Reported off-peak charging current in A                                                                               |
| Reported warm-up after full charge        | `sensor.growatt_thor_ev_charger_warm_up_after_full_charge`                                                                                                                                                                                                                                                                                     | Warm-up state read back from the charger                                                                              |
| Delayed charging time                     | `sensor.growatt_thor_ev_charger_delayed_charging_time`                                                                                                                                                                                                                                                                                         | Reported charger-side delay duration in seconds                                                                       |
| Reported power meter type                 | `sensor.growatt_thor_external_meter_power_meter_type`                                                                                                                                                                                                                                                                                          | Optional readback shadow of the configured external meter model                                                       |
| Reported power meter address              | `sensor.growatt_thor_external_meter_power_meter_address`                                                                                                                                                                                                                                                                                       | Optional readback shadow of the configured external Modbus address                                                    |
| Reported external sampling method         | `sensor.growatt_thor_external_meter_external_sampling_method`                                                                                                                                                                                                                                                                                  | Optional readback shadow of the external meter or current-transformer wiring method                                   |
| Electricity Price                         | `sensor.growatt_thor_ev_charger_electricity_price`                                                                                                                                                                                                                                                                                             | Configured electricity price using the Home Assistant system currency per kWh                                         |
| Last Session Energy                       | `sensor.growatt_thor_ev_charger_last_session_energy`                                                                                                                                                                                                                                                                                           | Energy from the most recently completed session                                                                       |
| Last Session Cost                         | `sensor.growatt_thor_ev_charger_last_session_cost`                                                                                                                                                                                                                                                                                             | Cost from the most recently completed session using the Home Assistant system currency                                |
| Last Session Duration                     | `sensor.growatt_thor_ev_charger_last_session_duration`                                                                                                                                                                                                                                                                                         | Full session duration displayed in hours; internal records and CSV exports retain minutes                             |
| Last Session Effective Charging Time      | `sensor.growatt_thor_ev_charger_last_session_effective_charging_duration`                                                                                                                                                                                                                                                                      | MeterValues-based time with actual energy transfer, displayed in hours; historical sessions remain unavailable        |
| Last Session Start                        | `sensor.growatt_thor_ev_charger_last_session_start`                                                                                                                                                                                                                                                                                            | Charging start timestamp                                                                                              |
| Last Session End                          | `sensor.growatt_thor_ev_charger_last_session_end`                                                                                                                                                                                                                                                                                              | Charging end timestamp                                                                                                |
| Last Session Plug Time                    | `sensor.growatt_thor_ev_charger_last_session_plug_time`                                                                                                                                                                                                                                                                                        | Cable connection timestamp                                                                                            |
| Last Session Unplug Time                  | `sensor.growatt_thor_ev_charger_last_session_unplug_time`                                                                                                                                                                                                                                                                                      | Cable disconnection timestamp                                                                                         |
| Last Session Transaction ID               | `sensor.growatt_thor_ev_charger_last_session_transaction_id`                                                                                                                                                                                                                                                                                   | OCPP transaction ID for the last session                                                                              |
| Last Session Charge Mode                  | `sensor.growatt_thor_ev_charger_last_session_charge_mode`                                                                                                                                                                                                                                                                                      | Translated Growatt authorization/charging mode for the last session; raw vendor code retained as an attribute         |
| Last Session Work Mode                    | `sensor.growatt_thor_ev_charger_last_session_work_mode`                                                                                                                                                                                                                                                                                        | Translated Growatt operating mode when its vendor code is confirmed; raw code retained as an attribute                |

External-meter measurements are polled in every charger working mode because
the same meter is used by load balancing and PV Linkage. A measurement remains
unavailable until the charger returns its field in `get_external_meterval`.
PV Linkage options are withheld while the charger reports an external-meter
Modbus fault or after three consecutive requests return no usable response.
One or two temporary timeouts do not block the mode. If PV Linkage is already
active, the current selection remains visible and is not changed automatically.

Warm-up support depends on the connected vehicle. The setting only allows a
compatible vehicle to continue drawing power after reaching full charge; it
does not directly control cabin or battery preconditioning.

The ShinePhone delayed-charging screen is inconsistent on the tested firmware:
both directions of its Random Delay switch wrote
`G_RandDelayChargeTime=0`. The integration therefore exposes only the reported
numeric delay and does not provide an unverified Random Delay control.

### Controls

| Entity name                      | Type   | Default entity ID                                                 | Purpose                                                                            |
| -------------------------------- | ------ | ----------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Max Current                      | Number | `number.growatt_thor_ev_charger_max_current`                      | Maximum charging current (6 A up to the reported model's 16/32/63 A limit)         |
| Loadbalancing limit              | Number | `number.growatt_thor_external_meter_loadbalancing_limit`          | Grid import limit (kW)                                                             |
| Electricity Price                | Number | `number.growatt_thor_ev_charger_electricity_price`                | Electricity tariff using the Home Assistant system currency per kWh                |
| Loadbalancing                    | Switch | `switch.growatt_thor_external_meter_loadbalancing`                | Enable or disable dynamic load balancing                                           |
| LCD Display                      | Switch | `switch.growatt_thor_ev_charger_lcd_display`                      | Enable or disable the charger display                                              |
| Start charging                   | Button | `button.growatt_thor_ev_charger_start_charging`                   | Manually request a charging session                                                |
| Stop charging                    | Button | `button.growatt_thor_ev_charger_stop_charging`                    | Stop the active charging session                                                   |
| Auto Charge Start Time           | Time   | `time.growatt_thor_ev_charger_auto_charge_start_time`             | Schedule start time; changes auto-apply through the write queue                    |
| Auto Charge Stop Time            | Time   | `time.growatt_thor_ev_charger_auto_charge_stop_time`              | Schedule stop time; changes auto-apply through the write queue                     |
| Charging strategy                | Select | `select.growatt_thor_ev_charger_charging_strategy`                | Select Fast, PV Linkage with grid import, solar-only PV Linkage+, or Off-Peak mode |
| External sampling method         | Select | `select.growatt_thor_external_meter_external_sampling_method`     | Select Power Meter, CT 2000:1, or CT 3000:1                                        |
| Power meter type                 | Select | `select.growatt_thor_external_meter_power_meter_type`             | Select the external Modbus meter model when Power Meter sampling is active         |
| Power meter address              | Number | `number.growatt_thor_external_meter_power_meter_address`          | Configure the Modbus address from 1 to 247 when Power Meter sampling is active     |
| PV Linkage grid import allowance | Number | `number.growatt_thor_ev_charger_pv_linkage_grid_import_allowance` | Grid power the charger may add in PV Linkage mode                                  |
| Warm-up after full charge        | Switch | `switch.growatt_thor_ev_charger_warm_up_after_full_charge`        | Allow compatible vehicles to continue drawing power for preheating or defrosting   |

Change the charger authorization mode from the [charging card](usage.md#local-charging-authorization).
Charging strategy has the select entity listed above. AP mode is available
under **Settings → Devices & Services → Growatt THOR → Configure → Maintenance: AP mode**,
with an explicit confirmation before activation.

Control availability follows the effective mode reported by the charger:

| Control                          | Available in                                                                        |
| -------------------------------- | ----------------------------------------------------------------------------------- |
| Charging strategy                | Any connected mode; PV Linkage choices require healthy external-meter communication |
| Load balancing and its limit     | Fast and Off-Peak                                                                   |
| External sampling method         | Any connected mode while no transaction is active                                   |
| Power meter type and address     | Any connected mode with Power Meter sampling while no transaction is active         |
| Automatic charging start/stop    | Fast                                                                                |
| PV Linkage grid import allowance | PV Linkage only; unavailable in solar-only PV Linkage+                              |
| Warm-up after full charge        | Any connected mode                                                                  |

Configuration controls and Start Charging are unavailable while the current
OCPP status is `Faulted`. The same guard runs again before queued writes are
executed. Stop Charging remains available so an active transaction can still be
ended as a safety action. The controls recover automatically with the next
non-fault status.

The charging-strategy select does not write `G_WorkingMode`; that key is a
readback of the effective mode. It uses the indirect writes captured from the
Growatt app: `G_SolarMode` selects Fast/PV Linkage variants and
`G_OffPeakEnable=1&Enable` selects Off-Peak. Home Assistant refreshes the
configuration after the charger has applied a change.

Growatt's naming is counterintuitive: PV Linkage allows the configured regular
grid import, while PV Linkage+ uses only solar surplus. Manual and Smart Boost
may still draw grid power in either PV variant.

Boost settings are staged locally and sent only after Apply PV Boost settings
is pressed. The button is available only when the complete draft differs from
the reported configuration. Manual Boost requires its complete time window;
Smart Boost requires both finish time and target energy. The period readback is
shared with Off-Peak mode, so the integration always writes the complete
applicable configuration instead of an isolated partial value.

## Entity semantics

The normalized **Last Session** values and their record key are restored after
a restart, so a repeated vendor session record is not counted twice. For retained
history and exports, see [sessions](sessions.md).

- Live measurements, session totals, and effective operating states are normal sensors.
- Values that can safely change charger behavior use `select`, `number`, `switch`, or `time` entities in the Configuration category.
- Retained vendor fields that are static, compound, or not safely writable are diagnostic sensors and keep their raw OCPP value as an attribute.
- Start and Stop are operational buttons rather than configuration entities.

Directly writable settings have a single enabled control entity. Their reported
read-only shadow sensors are disabled by default, while raw configuration values
and write acknowledgements remain available in the Home Assistant diagnostics
download. Control entities expose only stable attributes, so pending writes and
readback confirmations do not create repeated activity entries when the effective
setting did not change. A Home Assistant or integration reload may still produce
the standard initial `unavailable` to current-value transition.


## Example automations

Adapt entity IDs to your installation. Read [command outcomes and waiting](automation-resilience.md#9-expose-the-actual-outcome-of-a-command) before relying on service completion or optimistic entity values.

### Request a start from a surplus sensor

Use a sensor that measures available surplus, not total PV production. Adapt
the example threshold to the charger's phase count and minimum power. This
requests a start only; it does not regulate power or stop when surplus falls.
For charger-managed solar charging, use [PV Linkage](energy.md#pv-charging-dialog).

```yaml
automation:
  - alias: "Start EV charging with solar excess"
    trigger:
      - platform: numeric_state
        entity_id: sensor.solar_surplus_power
        above: 2000  # Example threshold in W; adapt to your installation
    condition:
      - condition: state
        entity_id: sensor.growatt_thor_ev_charger_status
        state: "preparing"
    action:
      - service: button.press
        target:
          entity_id: button.growatt_thor_ev_charger_start_charging
```

### Set the grid-import limit

The wallbox performs load balancing; this action sets its limit in kW. Use the
actual limit entity from your installation and check its supported mode and
availability. Do not continuously rewrite the limit from every meter update.

```yaml
action: number.set_value
target:
  entity_id: number.growatt_thor_external_meter_loadbalancing_limit
data:
  value: 6
```

---
