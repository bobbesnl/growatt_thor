import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  capabilities,
  commandInfo,
  elapsed,
  meterFresh,
  numeric,
  powerMaximum,
  resolveEntity,
  statusEntities,
  stateFor,
  vehicleConnection,
  restingDisplay,
  animateGauge,
} from '../src/shared/model';
import { makeData, entity, hass } from './fixtures';

const now = Date.parse('2026-09-09T12:00:00Z');

test('Gauge motion requires charging and fresh positive power with a known scale', () => {
  assert.equal(animateGauge('charging', true, 8300, 11), true);
  for (const state of [
    'preparing',
    'idle',
    'pv_wait',
    'pv_standby',
    'suspended_ev',
    'offline',
    'faulted',
  ]) {
    assert.equal(animateGauge(state, true, 8300, 11), false);
  }
  assert.equal(animateGauge('charging', false, 8300, 11), false);
  assert.equal(animateGauge('charging', true, null, 11), false);
  assert.equal(animateGauge('charging', true, 0, 11), false);
  assert.equal(animateGauge('charging', true, 8300, null), false);
});

test('Automatic gauge uses model and configured current, not measured active phases', () => {
  const config = { type: 'custom:growatt-thor-card' };
  const data = makeData({ rated_power_kw: 22, max_current_a: 32, configured_current_a: 16 });
  assert.equal(powerMaximum(data, config), 11);
  assert.equal(powerMaximum({ ...data, configured_current_a: 10 }, config), 6.9);
  assert.equal(powerMaximum({ ...data, configured_current_a: 32 }, config), 22);
  assert.equal(powerMaximum({ ...data, configured_current_a: 64 }, config), 22);
  assert.equal(powerMaximum({ ...data, configured_current_a: null }, config), 22);
  assert.equal(
    powerMaximum(
      { ...data, rated_power_kw: 7.4, nominal_phases: 1, configured_current_a: 32 },
      config,
    ),
    7.4,
  );
  assert.equal(powerMaximum({ ...data, rated_power_kw: 7.4, nominal_phases: 1 }, config), 3.7);
  assert.equal(powerMaximum({ ...data, currents_a: [16, 0, 0] }, config), 11);
  assert.equal(powerMaximum({ ...data, rated_power_kw: null }, config), null);
  assert.equal(powerMaximum({ ...data, rated_power_kw: null }, { ...config, max_power: 7.4 }), 7.4);
});

test('Rest display does not pretend missing measurements are zero or conceal charging faults', () => {
  assert.equal(restingDisplay('preparing', true, false, null), true);
  assert.equal(restingDisplay('charging', true, true, null), false);
  assert.equal(restingDisplay('preparing', false, false, null), false);
  assert.equal(restingDisplay('faulted', true, false, null), false);
  assert.equal(restingDisplay('preparing', true, false, 0), false);
});

test('Activation mode is distinct from strategy and gates manual start', () => {
  for (const mode of ['rfid_only', 'plug_and_charge', undefined, 'unexpected']) {
    const data = makeData({ auth_mode: mode, transaction_active: false });
    assert.equal(capabilities(hass, data, entity('preparing', data), true, false).start, false);
  }
  const data = makeData({ transaction_active: false });
  assert.equal(capabilities(hass, data, entity('preparing', data), true, false).start, true);
  assert.equal(
    capabilities(hass, makeData({ auth_mode: 'rfid_only' }), entity('charging'), true, false).stop,
    true,
  );
});

test('Vehicle presence is not inferred from the wallbox network connection', () => {
  assert.equal(vehicleConnection('preparing', true), 'vehicleConnected');
  assert.equal(vehicleConnection('charging', false), 'vehicleUnknown');
  assert.equal(vehicleConnection('available', true), 'vehicleDisconnected');
  assert.equal(vehicleConnection('idle', true), 'vehicleUnknown');
  assert.equal(vehicleConnection('faulted', true), 'vehicleUnknown');
  assert.equal(stateFor(entity('preparing'), true, makeData()).icon, 'mdi:timer-sand');
});

test('All OCPP states have a readable distinct presentation; offline wins over stale charging', () => {
  for (const state of [
    'charging',
    'available',
    'idle',
    'preparing',
    'suspended_ev',
    'suspended_evse',
    'finishing',
    'reserved',
    'unavailable',
    'faulted',
  ])
    assert.equal(stateFor(entity(state), true, makeData()).key, state);
  assert.equal(stateFor(entity('charging'), false, makeData()).key, 'offline');
  assert.equal(stateFor(entity('unknown'), true, makeData()).key, 'unknown');
});
test('PV wait is explicit only with evidence; vehicle wait is not PV wait or a fault', () => {
  const pv = makeData({
    working_mode: 'pv_linkage_plus',
    status_info: 'ChargeWait',
    error_code: 'EVCommunicationError',
  });
  assert.equal(stateFor(entity('suspended_ev'), true, pv).key, 'suspended_ev');
  assert.equal(stateFor(entity('preparing'), true, pv).key, 'pv_standby');
  assert.equal(stateFor(entity('suspended_evse'), true, pv).key, 'pv_standby');
  assert.equal(
    stateFor(entity('suspended_evse'), true, { ...pv, status_info: 'Wait for surplus' }).key,
    'pv_wait',
  );
  assert.equal(stateFor(entity('faulted'), true, pv).tone, 'red');
});
test('Meter freshness considers sample age and session boundary, not just receipt', () => {
  assert.equal(meterFresh(makeData(), now, '2026-09-09T11:59:59Z'), false);
  assert.equal(meterFresh(makeData(), now, '2026-09-09T11:59:50Z'), true);
  assert.equal(meterFresh(makeData(), now), true);
  assert.equal(meterFresh(makeData({ sample_at: null }), now), false);
  assert.equal(meterFresh(makeData({ sample_at: '2026-09-09T11:00:00Z' }), now), false);
  assert.equal(meterFresh(makeData({ session_started_at: '2026-09-09T12:00:00Z' }), now), false);
  assert.equal(meterFresh(makeData({ sample_at: '2026-09-10T12:00:00Z' }), now), false);
});
test('Start and stop respect connection, transaction, fault and unavailable controls', () => {
  assert.equal(capabilities(hass, makeData(), entity('unavailable'), true, false).limit, false);
  assert.equal(
    capabilities(hass, makeData({ transaction_active: false }), entity('unavailable'), true, false)
      .start,
    false,
  );
  assert.equal(capabilities(hass, makeData(), entity('unavailable'), true, false).stop, true); // Preserve stop for an ongoing transaction.
  assert.equal(capabilities(hass, makeData(), entity('charging'), false, false).limit, false);
  assert.equal(capabilities(hass, makeData(), entity('charging'), true, false).start, false);
  assert.equal(capabilities(hass, makeData(), entity('faulted'), true, false).stop, true);
  assert.equal(capabilities(hass, makeData(), entity('charging'), false, false).stop, false);
  assert.equal(capabilities(hass, makeData(), entity('charging'), true, true).stop, false);
  assert.equal(
    capabilities(hass, makeData({ transaction_active: false }), entity('preparing'), true, false)
      .start,
    true,
  );
  assert.equal(
    capabilities(
      { ...hass, states: {} },
      makeData({ transaction_active: false }),
      entity('preparing'),
      true,
      false,
    ).start,
    false,
  );
});
test('Queue and acceptance are not physical completion; reject and timeout are visible', () => {
  const data = makeData({
    command: { action: 'stop', state: 'accepted', updated_at: new Date(now).toISOString() },
  });
  assert.equal(commandInfo(data, 'charging', now).pending, true);
  assert.equal(commandInfo({ ...data, transaction_active: false }, 'idle', now).key, '');
  assert.equal(commandInfo(data, 'charging', now + 61000).key, 'commandUnconfirmed');
  assert.equal(
    commandInfo({ ...data, command: { ...data.command!, state: 'rejected' } }, 'charging', now).key,
    'commandRejected',
  );
});
test('Stable entry selection survives rename and does not pick another charger', () => {
  const e = entity('charging');
  assert.equal(
    resolveEntity(
      { ...hass, states: { renamed: e } },
      { type: 'custom:growatt-thor-card', entry_id: 'one', entity: 'sensor.old' },
    ),
    e,
  );
  assert.equal(
    resolveEntity(
      { ...hass, states: { renamed: e } },
      { type: 'custom:growatt-thor-card', entry_id: 'missing' },
    ),
    undefined,
  );
  assert.equal(
    resolveEntity(
      { ...hass, states: { one: e, two: entity('idle', makeData({ entry_id: 'two' })) } },
      { type: 'custom:growatt-thor-card' },
    ),
    undefined,
  );
});
test('Numbers, durations and hardware scales do not manufacture missing measurements', () => {
  assert.equal(numeric(null), null);
  assert.equal(numeric(NaN), null);
  assert.equal(numeric(Infinity), null);
  assert.equal(numeric(0), 0);
  assert.equal(elapsed(null, now), '—');
  assert.equal(elapsed('2026-09-09T10:30:00Z', now), '01:30');
  assert.equal(powerMaximum(makeData(), { type: 'custom:growatt-thor-card' }), 11);
  assert.equal(powerMaximum(makeData(), { type: 'custom:growatt-thor-card', max_power: 7.4 }), 7.4);
});

test('Status discovery ignores absent entities and unrelated attributes', () => {
  const status = entity('available');
  const state = {
    ...hass,
    states: {
      missing: undefined,
      status,
      unrelated: { entity_id: 'sensor.other', state: 'unknown', attributes: {} },
    },
  };
  assert.deepEqual(statusEntities(state), [status]);
  assert.equal(resolveEntity(state, { type: 'card', entry_id: 'one' }), status);
  assert.equal(resolveEntity(state, { type: 'card', entity: 'missing' }), undefined);
});
