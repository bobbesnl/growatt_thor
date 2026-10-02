# Troubleshooting and diagnostics

[Documentation](../README.md#documentation)

## Known firmware limitations

The Growatt Thor charger has **known firmware bugs** that can cause crashes and unexpected reboots, particularly during:

- Multiple rapid configuration changes
- Concurrent polling and command execution
- High message frequency on the OCPP connection

**Protective Measures Implemented:**

- Write queue with 20-second rate limiting
- Automatic polling pause during config writes
- Command deduplication for rapid UI changes
- Smart timing delays

⚠️ **Important**: While these protections significantly reduce crashes, they **cannot guarantee** complete stability due to Thor's firmware limitations.

**📢 Help Us Improve!**
Experiencing crashes or random reboots? Please [open an issue](https://github.com/bobbesnl/growatt_thor/issues) with:

- Thor model and firmware version, if known
- Enclosure layout, exterior controls, or PCB marking, if safely accessible
- Home Assistant logs (around crash time)
- Actions that triggered the reboot
- Relevant entity states before and after the reboot

Your feedback helps identify patterns and improve integration stability! 🙏

---

## Reporting a problem

If you encounter issues, please report bugs. Do not forget to send logs with your bug report.
Enable debug logging in configuration.yaml

```yaml
logger:
  default: warning
  logs:
    custom_components.growatt_thor: debug
    ocpp: info
```

### Charger Not Connecting

- **Check network connectivity**: Ping the charger from Home Assistant
- **Verify server URL**: Ensure correct IP address and port in Thor settings
- **Check firewall**: Port 9000 must be open
- **Check logs**: Settings → System → Logs → Filter by "growatt_thor" (enabled debug logging for this integration)
- **Restart charger**: Power cycle the Thor charger

### Polling Too Frequent / Too Slow

1. Go to **Settings → Devices & Services**
2. Click on **Growatt THOR** integration
3. Click **Configure**
4. Adjust **Grid Poll Interval**:
   - 30-60 seconds = recommended balance
   - 5-10 seconds = real-time (higher load)
   - 300-600 seconds = minimal load
5. The saved interval is applied to the running poll schedule; no restart is required.

### Thor Firmware Crash / Freezing

The firmware protections include:

- **Write queue system**: All writes are queued with 20-second minimum interval
- **20-second polling pause** after each configuration change (increased from 10s)
- **Sequential execution**: Multiple rapid changes are buffered and executed safely
- **Smart polling**: External-meter requests continue in every working mode; accepted configuration writes still pause polling for 20 seconds

If crashes still occur:

- Check logs for queued operations: `grep "Write queued" home-assistant.log`
- Increase poll interval to 60+ seconds
- Report issue with debug logs at [GitHub Issues](https://github.com/bobbesnl/growatt_thor/issues)
- Check Thor firmware version

### Configuration Changes Not Applied

If configuration changes don't seem to work:

- Check logs for queue status: `grep "Waiting.*before next write" home-assistant.log`
- The write queue may be processing previous changes (20-second interval)
- A queue of several writes can take longer than 20 seconds; inspect **Last command result** for the eventual outcome
- UI updates immediately (optimistic), but actual write may be queued

---

## Technical Details

### OCPP Implementation

- **Protocol**: OCPP 1.6J (JSON over WebSocket)
- **Supported messages**:
  - BootNotification, Heartbeat, StatusNotification
  - StartTransaction, StopTransaction, MeterValues
  - Authorize, DataTransfer (Growatt vendor extensions)
  - RemoteStartTransaction, RemoteStopTransaction
  - GetConfiguration, ChangeConfiguration
  - TriggerMessage

### Growatt-Specific Features

- `G_MaxCurrent` - Maximum charging current
- `G_ExternalLimitPower` - Load balancing limit
- `G_ExternalLimitPowerEnable` - Load balancing toggle
- `G_ChargerMode` - Charging mode
- `G_AutoChargeTime` - Scheduled charging times
- `get_external_meterval` - Grid meter data request
- `frozenrecord` / `currentrecord` - Session history

The integration keeps the last-known raw and normalized values returned by
`GetConfiguration`. These values are included in the Home Assistant diagnostics
download. Network identifiers, credentials, and unregistered keys are redacted
in that export; sensitive credentials are also excluded from active requests.
The same diagnostics include the latest complete `MeterValues` payload and the
latest Growatt `currentrecord` and `frozenrecord`. Unknown meter measurands and
vendor fields are retained without automatically creating entities for them.
Raw Growatt session query strings and values of unknown session fields are
redacted in the downloaded diagnostics. A separate `sessions` section combines
matching OCPP and Growatt data without replacing either raw source. Its
correlation status distinguishes sessions reported by both sources from
OCPP-only and Growatt-only records, and energy differences remain visible.

---

For command expiry, reconnects and uncertain results, see [automation resilience](automation-resilience.md).
