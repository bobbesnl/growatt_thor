import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  canRefresh,
  canScheduleReplace,
  liveGoalAvailable,
  liveTargetStatus,
  oneTimeGoalAvailable,
  scheduledGoalAvailable,
  TARGET_NOTICE_TTL_MS,
  targetNoticeVisible,
  validLiveTarget,
  validLiveEnergy,
  type TargetRequest,
} from '../src/targets/live';
import { makeData, entity, hass } from './fixtures';

const request: TargetRequest = {
  request_id: 'one',
  kind: 'energy',
  value: '1',
  state: 'target_accepted_waiting_for_plug',
  activation: 'plug_and_charge',
  connection_started_at: 'connection',
};
test('Live targets support ready PnC and cannot silently replace unknown or different targets', () => {
  const data = makeData({
    charging_target_pilot: true,
    transaction_active: false,
    auth_mode: 'plug_and_charge',
  });
  assert.equal(liveGoalAvailable(hass, entity('available', data), data), true);
  assert.equal(liveGoalAvailable(hass, entity('preparing', data), data), true);
  assert.equal(
    liveGoalAvailable(hass, entity('available', data), { ...data, transaction_active: true }),
    false,
  );
  assert.equal(canRefresh(request, 1), true);
  assert.equal(canRefresh(request, 2), false);
  assert.equal(canRefresh({ ...request, state: 'outcome_unknown' }, 1), false);
  for (const value of [null, 0, 101, 1.001, NaN]) assert.equal(validLiveEnergy(value), false);
  assert.equal(validLiveEnergy(1.01), true);
  assert.equal(validLiveTarget('duration', 5), true);
  assert.equal(validLiveTarget('duration', 5.5), false);
  assert.equal(validLiveTarget('budget', 1), true);
  assert.equal(validLiveTarget('budget', 0.99), false);
});
test('One-time reservations require Available while daily schedules accept Preparing', () => {
  const data = makeData({
    charging_target_pilot: true,
    transaction_active: false,
    auth_mode: 'home_assistant_rfid',
    working_mode: 'fast',
  });
  assert.equal(scheduledGoalAvailable(hass, entity('available', data), data), true);
  assert.equal(scheduledGoalAvailable(hass, entity('preparing', data), data), true);
  assert.equal(oneTimeGoalAvailable(hass, entity('available', data), data), true);
  assert.equal(oneTimeGoalAvailable(hass, entity('preparing', data), data), false);
  const plugData = { ...data, auth_mode: 'plug_and_charge' };
  assert.equal(scheduledGoalAvailable(hass, entity('available', plugData), plugData), true);
  assert.equal(scheduledGoalAvailable(hass, entity('preparing', plugData), plugData), true);
  assert.equal(canScheduleReplace(null, 'energy', 1), true);
  assert.equal(canScheduleReplace({ ...request, state: 'scheduled' }, 'energy', 2), false);
  assert.equal(canScheduleReplace({ ...request, state: 'scheduled_cancelled' }, 'energy', 2), true);
  assert.equal(
    canScheduleReplace({ ...request, state: 'blocked_before_target' }, 'energy', 2),
    true,
  );
  assert.equal(canScheduleReplace({ ...request, state: 'outcome_unknown' }, 'energy', 1), false);
});
test('Live target separates queued, accepted, charging and stale retained requests', () => {
  const data = makeData({
    charging_target: request,
    connection_started_at: 'connection',
    auth_mode: 'plug_and_charge',
    transaction_active: false,
  });
  assert.equal(liveTargetStatus(data), 'goalLiveAccepted');
  assert.equal(liveTargetStatus({ ...data, transaction_active: true }), 'goalLiveCharging');
  assert.equal(liveTargetStatus({ ...data, auth_mode: 'rfid_only' }), 'goalLiveRetained');
  assert.equal(
    liveTargetStatus({
      ...data,
      charging_target: { ...request, state: 'active', enforcement_verified: true },
    }),
    'goalLiveChargingVerified',
  );
  assert.equal(liveTargetStatus({ ...data, connection_started_at: 'new' }), 'goalLiveRetained');
  assert.equal(
    liveTargetStatus({ ...data, charging_target: { ...request, state: 'queued' } }),
    'goalLiveQueued',
  );
  assert.equal(
    liveTargetStatus({ ...data, charging_target: { ...request, state: 'outcome_unknown' } }),
    'goalLiveUncertain',
  );
  assert.equal(
    liveTargetStatus({ ...data, charging_target: { ...request, state: 'scheduled' } }),
    'goalLiveScheduled',
  );
  assert.equal(
    liveTargetStatus({
      ...data,
      charging_target: { ...request, state: 'scheduled', recurrence: 'daily' },
    }),
    'goalLiveScheduledDaily',
  );
  assert.equal(
    liveTargetStatus({ ...data, charging_target: { ...request, state: 'scheduled_missed' } }),
    'goalLiveScheduleMissed',
  );
  assert.equal(
    liveTargetStatus({ ...data, charging_target: { ...request, state: 'blocked_before_target' } }),
    'goalLiveScheduleBlocked',
  );
});

test('Only safe terminal target notices expire from the main card', () => {
  const now = Date.parse('2026-09-11T18:00:00Z');
  const terminal = {
    ...request,
    state: 'blocked_before_target',
    updated_at: new Date(now - TARGET_NOTICE_TTL_MS + 1).toISOString(),
  };

  assert.equal(targetNoticeVisible(null, now), false);
  assert.equal(targetNoticeVisible(terminal, now), true);
  for (const state of [
    'blocked_before_target',
    'completed',
    'scheduled_cancelled',
    'scheduled_missed',
    'target_rejected',
  ]) {
    assert.equal(
      targetNoticeVisible(
        { ...terminal, state, updated_at: new Date(now - TARGET_NOTICE_TTL_MS).toISOString() },
        now,
      ),
      false,
    );
  }
  assert.equal(
    targetNoticeVisible({ ...terminal, state: 'outcome_unknown', updated_at: '2020-01-01' }, now),
    true,
  );
  assert.equal(targetNoticeVisible({ ...terminal, updated_at: undefined }, now), true);
});
