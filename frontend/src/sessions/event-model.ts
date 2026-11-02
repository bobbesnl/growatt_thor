import { energyStopReason } from '../shared/energy-stop';
import { translate } from '../shared/strings';
import type { SessionEventType } from '../shared/types';
import { sessionTranslate, type SessionKey } from './locales';
import type { SessionEventTone } from './model';

const EVENT_LABELS: Record<SessionEventType, SessionKey> = {
  plugged_in: 'eventPluggedIn',
  transaction_started: 'eventTransactionStarted',
  energy_flow_started: 'eventEnergyFlowStarted',
  charging_paused: 'eventChargingPaused',
  energy_flow_stopped: 'eventEnergyFlowStopped',
  stop_requested: 'eventStopRequested',
  transaction_stopped: 'eventTransactionStopped',
  unplugged: 'eventUnplugged',
};

export function sessionEventLabel(
  types: SessionEventType[],
  provisional: boolean,
  language: string,
): string {
  const t = sessionTranslate(language);
  const label = types.map((type) => t(EVENT_LABELS[type])).join(' · ');
  return provisional ? `${label} (${t('eventProvisional')})` : label;
}

/** Status reasons share the charger's translated vocabulary. Other OCPP reasons stay intact. */
export function sessionEventReason(
  reason: string | undefined,
  language: string,
): string | undefined {
  if (reason === 'energy_guard_battery' || reason === 'energy_guard_grid')
    return energyStopReason(reason.replace('energy_guard_', ''), language);
  return reason && ['suspended_ev', 'suspended_evse'].includes(reason)
    ? translate(language)(reason)
    : reason;
}

/** One palette for chart markers and the compact event list, in both themes. */
export function sessionEventColors(dark: boolean): Record<SessionEventTone, string> {
  return {
    lime: '#8bc53f',
    blue: dark ? '#79c7f2' : '#2f7fb8',
    amber: dark ? '#efbe6b' : '#b36f14',
    coral: dark ? '#f1966f' : '#db7447',
    neutral: dark ? '#a4b3a6' : '#6c7b72',
  };
}
