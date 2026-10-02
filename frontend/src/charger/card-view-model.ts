import {
  animateGauge,
  capabilities,
  clamp,
  commandInfo,
  meterFresh,
  numeric,
  powerMaximum,
  restingDisplay,
  stateFor,
  vehicleConnection,
} from '../shared/model';
import { entityNumber, sessionDisplay } from '../sessions/model';
import { powerFlowView } from '../energy/model';
import { translate } from '../shared/strings';
import type { CardConfig, CardData, Entity, Hass } from '../shared/types';

export interface LocalCommandState {
  issuedAt: number;
  sending: boolean;
}

const LOCAL_ACK_GRACE_MS = 10_000;
const ACK_CLOCK_TOLERANCE_MS = 1_000;

/** Derive display data without DOM access, service calls or mutations of HA state. */
export function buildCardViewModel(
  hass: Hass,
  config: CardConfig,
  entity: Entity,
  data: CardData,
  now: number,
  localCommand: LocalCommandState,
) {
  const t = translate(hass.language || hass.locale?.language);
  const dark = config.theme === 'dark' || (config.theme !== 'light' && !!hass.themes?.darkMode);
  const connected = hass.connected !== false && entity.attributes.connected === true;
  const status = stateFor(entity, connected, data);
  const inactive = ['offline', 'unavailable'].includes(status.key);
  const vehicle = vehicleConnection(entity.state, connected);
  const auth = ['home_assistant_rfid', 'rfid_only', 'plug_and_charge'].includes(
    data.auth_mode || '',
  )
    ? data.auth_mode!
    : 'authUnknown';
  const suspended = ['suspended_ev', 'suspended_evse'].includes(entity.state);
  // A reading from before suspension must not keep showing the previous load.
  // Only current telemetry may drive the gauge and phase bars.
  const fresh =
    connected &&
    !inactive &&
    meterFresh(data, now, data.transaction_active && !suspended ? undefined : entity.last_changed);
  const idle =
    connected &&
    !data.transaction_active &&
    ['available', 'idle', 'finishing'].includes(entity.state);
  const power = fresh ? numeric(data.power_w) : null;
  const expectedTelemetryPause =
    connected &&
    power === null &&
    ['pv_wait', 'pv_standby', 'suspended_ev', 'suspended_evse'].includes(status.key);
  const resting =
    restingDisplay(entity.state, connected, data.transaction_active, power) ||
    expectedTelemetryPause;
  const kw = power === null ? null : power / 1000;
  const maxPower = powerMaximum(data, config);
  const animate = animateGauge(status.key, fresh, power, maxPower);
  // Zero here is only the SVG gauge's resting position. Keep kw === null so
  // templates can show standby/missing data instead of inventing a measured 0 kW.
  const fraction = maxPower ? clamp(((kw || 0) / maxPower) * 100) : 0;
  const currents = [0, 1, 2].map((i) => (fresh ? numeric(data.currents_a?.[i]) : null));
  const active = currents.filter((c) => c !== null && c > 0.3).length;
  const complete = currents.every((c) => c !== null);
  const format = (value: number | null, digits = 1) =>
    value === null
      ? '—'
      : value.toLocaleString(hass.language || 'en', {
          minimumFractionDigits: digits,
          maximumFractionDigits: digits,
        });
  // Bridge the short gap between the service call and the first backend update.
  const info = commandInfo(data, entity.state, now);
  const awaitingState =
    localCommand.issuedAt > 0 &&
    now - localCommand.issuedAt < LOCAL_ACK_GRACE_MS &&
    !(Date.parse(data.command?.updated_at || '') >= localCommand.issuedAt - ACK_CLOCK_TOLERANCE_MS);
  const caps = capabilities(
    hass,
    data,
    entity,
    connected,
    info.pending || localCommand.sending || awaitingState,
  );
  const fault = hass.states[data.entities?.last_charger_fault];
  const session = sessionDisplay(hass, data, now);
  const limit = hass.states[data.entities?.max_current];
  const faultMessage =
    status.key === 'faulted'
      ? data.status_info || fault?.attributes.message || data.error_code
      : null;
  const meterWarning =
    connected &&
    data.working_mode?.startsWith('pv_linkage') &&
    ['fault', 'faulted', 'modbus_fault', 'timeout', 'stale'].includes(data.external_meter_health);
  const powerFlow = powerFlowView(data, kw, maxPower, connected && !inactive, now);

  return {
    hass,
    config,
    entity,
    data,
    t,
    dark,
    connected,
    status,
    inactive,
    vehicle,
    auth,
    fresh,
    idle,
    resting,
    expectedTelemetryPause,
    kw,
    maxPower,
    animate,
    fraction,
    currents,
    active,
    complete,
    format,
    info,
    caps,
    fault,
    ...session,
    currentLimit: entityNumber(limit),
    faultMessage,
    meterWarning,
    powerFlow,
    now,
  };
}
export type CardViewModel = ReturnType<typeof buildCardViewModel>;
