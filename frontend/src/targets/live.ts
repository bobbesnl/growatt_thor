import type { GoalKind, GoalRecurrence } from './model';
import type { CardData, Entity, Hass } from '../shared/types';

export interface TargetRequest {
  request_id: string;
  kind: GoalKind;
  value: string;
  state: string;
  activation: string;
  recurrence?: GoalRecurrence;
  connection_started_at?: string;
  scheduled_for?: string;
  last_run_at?: string;
  last_run_state?: string;
  updated_at?: string;
  enforcement_verified?: boolean;
}
export interface LiveGoal {
  available: boolean;
  scheduleOnceAvailable: boolean;
  scheduleDailyAvailable: boolean;
  request?: TargetRequest | null;
  status: string;
  save(
    kind: GoalKind,
    value: number,
    startAt?: string,
    recurrence?: GoalRecurrence,
    replaceId?: string,
  ): Promise<void>;
  cancel?(requestId: string): Promise<void>;
}

const replaceableStates = new Set([
  'blocked_before_target',
  'completed',
  'scheduled_cancelled',
  'scheduled_missed',
  'target_rejected',
]);
const waitingStates = new Set([
  'target_accepted_waiting_for_rfid',
  'target_accepted_waiting_for_plug',
]);

const transientTerminalStates = new Set([
  'blocked_before_target',
  'completed',
  'scheduled_cancelled',
  'scheduled_missed',
  'target_rejected',
]);

/**
 * Completed and safely replaceable requests remain in backend history, but
 * should not occupy the main card indefinitely. Ambiguous outcomes deliberately
 * remain visible until the user resolves or replaces them.
 */
export const TARGET_NOTICE_TTL_MS = 30 * 60 * 1000;

export function targetNoticeVisible(
  request: TargetRequest | null | undefined,
  now: number,
): boolean {
  if (!request) return false;
  if (!transientTerminalStates.has(request.state)) return true;

  const updatedAt = Date.parse(request.updated_at || '');
  // Legacy records without a timestamp remain visible instead of being hidden
  // on an assumption about their age.
  if (!Number.isFinite(updatedAt)) return true;
  return now - updatedAt < TARGET_NOTICE_TTL_MS;
}

export function canReplace(
  request: TargetRequest | null | undefined,
  kind: GoalKind,
  value: number,
): boolean {
  if (!request) return true;
  if (replaceableStates.has(request.state)) return true;
  return (
    request.kind === kind && Number(request.value) === value && waitingStates.has(request.state)
  );
}

export function canScheduleReplace(
  request: TargetRequest | null | undefined,
  kind: GoalKind,
  value: number,
): boolean {
  return canReplace(request, kind, value);
}

export function canRefresh(
  request: TargetRequest | null | undefined,
  value: number,
  kind: GoalKind = 'energy',
): boolean {
  return canReplace(request, kind, value);
}

export function validLiveTarget(kind: GoalKind, value: number | null): boolean {
  if (value === null || !Number.isFinite(value)) return false;
  if (kind === 'duration') return Number.isInteger(value) && value >= 1 && value <= 1440;
  const hundredths = Math.abs(value * 100 - Math.round(value * 100)) < 1e-8;
  if (kind === 'budget') return hundredths && value >= 1 && value <= 1000;
  return hundredths && value >= 0.01 && value <= 100;
}

export function validLiveEnergy(value: number | null): boolean {
  return validLiveTarget('energy', value);
}

function baseAvailable(hass: Hass, entity: Entity, data: CardData): boolean {
  return (
    data.charging_target_pilot === true &&
    hass.connected !== false &&
    entity.attributes.connected === true &&
    !data.transaction_active &&
    data.working_mode === 'fast'
  );
}

export function liveGoalAvailable(hass: Hass, entity: Entity, data: CardData): boolean {
  const ready = ['available', 'preparing'].includes(entity.state);
  const supportedMode = ['plug_and_charge', 'home_assistant_rfid', 'rfid_only'].includes(
    data.auth_mode || '',
  );
  return baseAvailable(hass, entity, data) && ready && supportedMode;
}

export function scheduledGoalAvailable(hass: Hass, entity: Entity, data: CardData): boolean {
  return (
    baseAvailable(hass, entity, data) &&
    ['available', 'preparing'].includes(entity.state) &&
    ['plug_and_charge', 'home_assistant_rfid'].includes(data.auth_mode || '')
  );
}

export function oneTimeGoalAvailable(hass: Hass, entity: Entity, data: CardData): boolean {
  return scheduledGoalAvailable(hass, entity, data) && entity.state === 'available';
}

export function liveTargetStatus(data: CardData): string {
  const request = data.charging_target;
  if (!request) return 'goalLiveNoTarget';
  if (request.state === 'scheduled')
    return request.recurrence === 'daily' ? 'goalLiveScheduledDaily' : 'goalLiveScheduled';
  if (request.state === 'scheduled_cancelled') return 'goalLiveScheduleCancelled';
  if (request.state === 'scheduled_missed') return 'goalLiveScheduleMissed';
  if (request.state === 'blocked_before_target') return 'goalLiveScheduleBlocked';
  if (request.state === 'completed') return 'goalLiveCompleted';
  if (request.state === 'active')
    return request.enforcement_verified ? 'goalLiveChargingVerified' : 'goalLiveCharging';
  if (
    request.connection_started_at &&
    request.connection_started_at !== data.connection_started_at &&
    !['reservation_queued', 'scheduled'].includes(request.state)
  )
    return 'goalLiveRetained';
  if (request.state === 'target_accepted_waiting_for_plug' && data.auth_mode !== 'plug_and_charge')
    return 'goalLiveRetained';
  if (request.state === 'target_accepted_waiting_for_plug')
    return data.transaction_active ? 'goalLiveCharging' : 'goalLiveAccepted';
  if (request.state === 'target_accepted_waiting_for_rfid' && data.auth_mode !== 'rfid_only')
    return 'goalLiveRetained';
  if (request.state === 'target_accepted_waiting_for_rfid') return 'goalLiveAcceptedRfid';
  if (
    [
      'queued',
      'reservation_queued',
      'sending_target',
      'target_accepted',
      'sending_reservation',
      'sending_start',
      'cancellation_queued',
      'sending_cancellation',
    ].includes(request.state)
  )
    return 'goalLiveQueued';
  if (request.state === 'start_accepted') return 'goalLiveStartAccepted';
  if (request.state === 'reservation_rejected_target_may_remain')
    return 'goalLiveReservationRejected';
  if (request.state === 'cancellation_rejected_reservation_may_remain')
    return 'goalLiveCancellationRejected';
  return 'goalLiveUncertain';
}
