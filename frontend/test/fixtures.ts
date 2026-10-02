import type { CardData, Entity, Hass } from '../src/shared/types';
export const makeData = (extra: Partial<CardData> = {}): CardData => ({
  schema: 1,
  entry_id: 'one',
  entities: {
    start_charging: 'button.start',
    stop_charging: 'button.stop',
    max_current: 'number.limit',
  },
  working_mode: 'fast',
  auth_mode: 'home_assistant_rfid',
  transaction_active: true,
  session_started_at: '2026-09-09T10:00:00Z',
  session_energy_kwh: 12.4,
  meter_received_at: '2026-09-09T11:59:55Z',
  sample_at: '2026-09-09T11:59:54Z',
  meter_stale_after: 180,
  power_w: 8300,
  currents_a: [12, 11.8, 12.2],
  max_current_a: 16,
  rated_power_kw: 11,
  nominal_phases: 3,
  configured_current_a: 16,
  status_info: null,
  error_code: null,
  external_meter_health: 'healthy',
  power_flow: {
    received_at: '2026-09-09T11:59:55Z',
    stale_after_s: 95,
    grid_w: -1200,
    grid_sign: 'positive_import',
    grid_import_limit_kw: 2,
  },
  ...extra,
});
export const entity = (state: string, data = makeData()): Entity => ({
  entity_id: 'sensor.renamed',
  state,
  attributes: { connected: true, thor_card: data },
});
export const hass: Hass = {
  states: {
    'button.start': { entity_id: 'button.start', state: 'unknown', attributes: {} },
    'button.stop': { entity_id: 'button.stop', state: 'unknown', attributes: {} },
    'number.limit': { entity_id: 'number.limit', state: '16', attributes: {} },
  },
  callService: async () => {},
};
