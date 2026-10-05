import type { CardConfig, CardData, Entity, Hass, Status, ThorStatusEntity } from './types';

export const clamp = (value: number, max = 100) => Math.min(max, Math.max(0, value));
export const numeric = (v: unknown): number | null =>
  typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : null;
export function statusEntities(hass: Hass): ThorStatusEntity[] {
  return Object.values(hass.states ?? {}).filter(
    (entity): entity is ThorStatusEntity => entity?.attributes.thor_card?.schema === 1,
  );
}
export function resolveEntity(hass: Hass, config: CardConfig): Entity | undefined {
  if (config.entry_id)
    return statusEntities(hass).find((e) => e.attributes.thor_card.entry_id === config.entry_id);
  if (config.entity) return hass.states?.[config.entity];
  const candidates = statusEntities(hass);
  return candidates.length === 1 ? candidates[0] : undefined;
}
export function stateFor(entity: Entity, connected: boolean, data: CardData): Status {
  const state = entity.state;
  const fault = state === 'faulted';
  if (!connected)
    return { key: 'offline', tone: 'neutral', icon: 'mdi:lan-disconnect', hint: 'offlineHint' };
  if (fault)
    return { key: 'faulted', tone: 'red', icon: 'mdi:alert-octagon-outline', hint: 'faultHint' };
  if (state === 'unavailable')
    return { key: 'unavailable', tone: 'neutral', icon: 'mdi:cancel', hint: 'unavailableHint' };
  const pv = data.working_mode?.startsWith('pv_linkage');
  if (['preparing', 'suspended_evse'].includes(state) && pv) {
    const explicit = /surplus|wait.*(?:solar|pv)|(?:solar|pv).*wait/i.test(data.status_info || '');
    if (explicit)
      return { key: 'pv_wait', tone: 'amber', icon: 'mdi:white-balance-sunny', hint: 'pvWaitHint' };
    // ChargeWait also occurs before StartTransaction. It signals readiness,
    // but does not establish that missing PV surplus is the only blocking reason.
    return {
      key: 'pv_standby',
      tone: 'amber',
      icon: 'mdi:weather-partly-cloudy',
      hint: 'pvStandbyHint',
    };
  }
  const statuses: Record<string, Status> = {
    charging: { key: 'charging', tone: 'green', icon: 'mdi:lightning-bolt', hint: 'chargingHint' },
    available: {
      key: 'available',
      tone: 'neutral',
      icon: 'mdi:ev-plug-type2',
      hint: 'availableHint',
    },
    idle: { key: 'idle', tone: 'neutral', icon: 'mdi:power-sleep', hint: 'idleHint' },
    preparing: { key: 'preparing', tone: 'blue', icon: 'mdi:timer-sand', hint: 'preparingHint' },
    suspended_ev: {
      key: 'suspended_ev',
      tone: 'amber',
      icon: 'mdi:car-clock',
      hint: 'vehicleWaitHint',
    },
    suspended_evse: {
      key: 'suspended_evse',
      tone: 'amber',
      icon: 'mdi:pause-circle-outline',
      hint: 'stationWaitHint',
    },
    finishing: {
      key: 'finishing',
      tone: 'blue',
      icon: 'mdi:check-circle-outline',
      hint: 'finishingHint',
    },
    reserved: { key: 'reserved', tone: 'blue', icon: 'mdi:lock-outline', hint: 'reservedHint' },
  };
  return (
    statuses[state] || {
      key: 'unknown',
      tone: 'neutral',
      icon: 'mdi:help-circle-outline',
      hint: 'unknownHint',
    }
  );
}
export function meterFresh(data: CardData, now: number, stateChanged?: string): boolean {
  // Arrival time alone is insufficient: a freshly delivered packet may contain
  // an old sample. Both timestamps must be recent before old power can look live again.
  const received = Date.parse(data.meter_received_at || '');
  const sample = Date.parse(data.sample_at || '');
  const threshold = (data.meter_stale_after || 180) * 1000;
  return (
    Number.isFinite(received) &&
    now - received <= threshold &&
    received <= now + 60000 &&
    Number.isFinite(sample) &&
    now - sample <= threshold &&
    sample <= now + 60000 &&
    (!data.session_started_at || received >= Date.parse(data.session_started_at)) &&
    (!stateChanged ||
      !Number.isFinite(Date.parse(stateChanged)) ||
      sample >= Date.parse(stateChanged))
  );
}
export function powerMaximum(data: CardData, config: CardConfig): number | null {
  if (config.max_power) return config.max_power;
  const rated = numeric(data.rated_power_kw);
  const phases = data.nominal_phases;
  if (!rated || ![1, 3].includes(phases || 0)) return null;
  const current = numeric(data.configured_current_a);
  if (!current) return rated;
  // Nominal 230 V per phase: a stable display ceiling, not an electrical limit.
  return (
    Math.round(
      Math.min(rated, (phases! * 230 * Math.min(current, data.max_current_a)) / 1000) * 10,
    ) / 10
  );
}

export function restingDisplay(
  state: string,
  connected: boolean,
  active: boolean,
  power: number | null,
) {
  return (
    connected &&
    !active &&
    power === null &&
    ['available', 'idle', 'preparing', 'finishing', 'reserved'].includes(state)
  );
}
export function animateGauge(
  state: string,
  fresh: boolean,
  power: number | null,
  maximum: number | null,
) {
  return (
    state === 'charging' && fresh && power !== null && power > 0 && maximum !== null && maximum > 0
  );
}
export function elapsed(start: string | null, now: number): string {
  const at = Date.parse(start || '');
  if (!Number.isFinite(at) || at > now) return '—';
  const minutes = Math.floor((now - at) / 60000);
  return `${Math.floor(minutes / 60)
    .toString()
    .padStart(2, '0')}:${(minutes % 60).toString().padStart(2, '0')}`;
}
export function commandInfo(data: CardData, state: string, now: number) {
  const command = data.command;
  if (!command) return { pending: false, key: '' };
  const age = now - Date.parse(command.updated_at);
  if (!Number.isFinite(age) || age > 180000 || age < -60000) return { pending: false, key: '' };
  if (command.state === 'error' || command.state === 'rejected')
    return {
      pending: false,
      key: command.reason === 'local_authorization_denied' ? 'localStartDenied' : 'commandRejected',
    };
  const complete =
    command.action === 'start'
      ? state === 'charging'
      : !data.transaction_active &&
        ['idle', 'available', 'finishing', 'preparing', 'suspended_ev', 'suspended_evse'].includes(
          state,
        );
  if (complete) return { pending: false, key: '' };
  if (age > 60000) return { pending: false, key: 'commandUnconfirmed' };
  return { pending: true, key: command.state === 'accepted' ? 'commandAccepted' : 'commandQueued' };
}
export function capabilities(
  hass: Hass,
  data: CardData,
  entity: Entity,
  connected: boolean,
  pending: boolean,
) {
  const ready = (key: string) => {
    const target = hass.states[data.entities?.[key]];
    return !!target && target.state !== 'unavailable'; // Button state 'unknown' is normal before its first press.
  };
  return {
    start:
      connected &&
      (data.auth_mode === 'home_assistant_rfid' ||
        (data.auth_mode === 'plug_and_charge' &&
          ['preparing', 'suspended_ev', 'suspended_evse'].includes(entity.state))) &&
      !pending &&
      !data.transaction_active &&
      ['available', 'idle', 'preparing', 'suspended_ev', 'suspended_evse'].includes(entity.state) &&
      ready('start_charging'),
    stop:
      connected &&
      !pending &&
      (data.transaction_active || entity.state === 'charging') &&
      ready('stop_charging'),
    limit: connected && !['faulted', 'unavailable'].includes(entity.state) && ready('max_current'),
  };
}

export function vehicleConnection(state: string, connected: boolean) {
  if (!connected) return 'vehicleUnknown';
  if (state === 'available') return 'vehicleDisconnected';
  if (['preparing', 'charging', 'suspended_ev', 'suspended_evse', 'finishing'].includes(state))
    return 'vehicleConnected';
  return 'vehicleUnknown'; // OCPP connectivity is not cable/vehicle presence.
}
