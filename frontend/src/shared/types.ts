/** Known Home Assistant attributes; unrelated integration attributes stay opaque. */
export interface EntityAttributes {
  thor_card?: CardData;
  connected?: boolean;
  options?: string[];
  unit_of_measurement?: string;
  friendly_name?: string;
  message?: string;
  [key: string]: unknown;
}
export interface Entity {
  entity_id: string;
  state: string;
  attributes: EntityAttributes;
  last_changed?: string;
}
export interface ThorStatusEntity extends Entity {
  attributes: EntityAttributes & { thor_card: CardData };
}
export interface Hass {
  states: Record<string, Entity | undefined>;
  language?: string;
  locale?: { language?: string };
  themes?: { darkMode?: boolean };
  connected?: boolean;
  callService(domain: string, service: string, data: Record<string, unknown>): Promise<unknown>;
  callWS?<T>(message: Record<string, unknown>): Promise<T>;
}
export interface CardConfig {
  type: string;
  entity?: string;
  entry_id?: string;
  name?: string;
  max_power?: number;
  theme?: 'auto' | 'light' | 'dark';
  show_image?: boolean;
  show_phases?: boolean;
  show_session?: boolean;
}
export interface SessionCardConfig {
  type: string;
  entity?: string;
  entry_id?: string;
  name?: string;
  theme?: 'auto' | 'light' | 'dark';
  rows?: number;
  show_curve?: boolean;
  show_identifier?: boolean;
}
export type SessionEventType =
  | 'plugged_in'
  | 'transaction_started'
  | 'energy_flow_started'
  | 'charging_paused'
  | 'energy_flow_stopped'
  | 'stop_requested'
  | 'transaction_stopped'
  | 'unplugged';
export interface SessionEvent {
  type: SessionEventType;
  at: string;
  source: 'ocpp' | 'growatt' | 'meter' | 'home_assistant';
  certainty: 'observed' | 'derived' | 'provisional';
  reason?: string;
}
export interface SessionItem {
  session_id: string | null;
  active?: boolean;
  start_time: string | null;
  end_time: string | null;
  energy_kwh: number | null;
  energy_source?: 'ocpp_meter' | 'power_fallback' | null;
  green_energy_kwh: number | null;
  source_energy_kwh?: {
    direct_solar: number;
    direct_grid: number;
    battery_unknown: number;
    unknown: number;
  } | null;
  effective_grid_cost?: number | null;
  accounting_coverage?: number | null;
  accounting_quality?: 'measured' | 'derived' | 'declared' | 'unknown' | null;
  accounting_policy?: { id: string; version: number; topology?: string | null } | null;
  cost: number | null;
  duration_minutes: number | null;
  authorized_identifier: string | null;
  power_curve?: [string, number][];
  /** Whether retained chart details can be loaded on demand. */
  detail_available?: boolean;
  /** Sum of the valid phase-current samples; not a charger current setpoint. */
  measured_current_sum_curve_a?: [string, number][];
  /** Reported or accepted G_MaxCurrent history; the limit applies per phase. */
  configured_current_limit_curve_a?: [string, number][];
  /** Whole-site PV surplus before EV charging and battery dispatch; context, not source allocation. */
  site_pv_surplus_curve_w?: [string, number][];
  /** Non-EV household consumption used to explain changes in available PV surplus. */
  site_house_load_curve_w?: [string, number][];
  /** Whole-site battery flow: positive discharge, negative charging. */
  site_battery_curve_w?: [string, number][];
  /** Optional PoC contract for observed or explicitly qualified session events. */
  events?: SessionEvent[];
}
export interface SessionHistoryData {
  schema: number;
  items: SessionItem[];
  total_energy_kwh: number;
  total_green_energy_kwh: number | null;
  total_cost: number;
  total_count: number;
}
export interface SessionDetailResponse {
  schema: number;
  item: SessionItem;
}
export interface PowerFlowData {
  received_at: string | null;
  stale_after_s: number;
  /** Signed net power at the grid connection: positive import, negative export. */
  grid_w: number | null;
  grid_sign: 'positive_import';
  grid_import_limit_kw: number | null;
  /** Future direct PV generation; positive means power supplied to the site. */
  solar_w?: number | null;
  /** Future battery flow; positive discharge, negative charging. */
  battery_w?: number | null;
  battery_received_at?: string | null;
  battery_sign?: 'positive_discharge';
  /**
   * Optional charger-source allocation calculated by the backend. Values are
   * non-negative contributions to the current charger power, not whole-site
   * PV production or battery flow. Missing power is rendered as unknown.
   */
  charging_sources?: {
    solar_w?: number | null;
    battery_w?: number | null;
    grid_w?: number | null;
    unknown_w?: number | null;
  };
}
export interface CardData {
  charging_target_pilot?: boolean;
  charging_target?: import('../targets/live').TargetRequest | null;
  connection_started_at?: string;
  schema: number;
  entry_id: string;
  entities: Record<string, string>;
  working_mode: string | null;
  auth_mode?: string | null;
  transaction_active: boolean;
  session_started_at: string | null;
  session_energy_kwh: number | null;
  meter_received_at: string | null;
  meter_stale_after: number;
  sample_at: string | null;
  power_w: number | null;
  currents_a: (number | null)[];
  max_current_a: number;
  nominal_phases?: number | null;
  rated_power_kw?: number | null;
  configured_current_a?: number | null;
  status_info: string | null;
  error_code: string | null;
  external_meter_health: string;
  power_flow?: PowerFlowData;
  pv_linkage?: PvLinkageData;
  command?: { action: 'start' | 'stop'; state: string; updated_at: string };
  sessions?: SessionHistoryData;
}
export interface PvLinkageData {
  working_mode: 'pv_linkage' | 'pv_linkage_plus';
  grid_import_limit_kw: number | null;
  boost_mode: 'disabled' | 'manual' | 'smart';
  manual_start: string | null;
  manual_end: string | null;
  smart_finish: string | null;
  smart_target_energy_kwh: number | null;
  draft_dirty: boolean;
  blocked_reason: string | null;
  last_apply?: {
    status: 'success' | 'failed' | 'partial' | 'uncertain';
    completed_steps: number;
    total_steps: number;
  } | null;
}
export type Tone = 'green' | 'amber' | 'red' | 'blue' | 'neutral';
export interface Status {
  key: string;
  tone: Tone;
  icon: string;
  hint: string;
}
declare global {
  interface Window {
    customCards?: Record<string, unknown>[];
  }
  const __CARD_VERSION__: string;
  const __SHARED_TRANSLATIONS__: Record<string, Record<string, string>>;
}
