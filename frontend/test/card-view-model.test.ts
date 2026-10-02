import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildCardViewModel } from '../src/charger/card-view-model';
import { entityNumber, sessionDisplay, storedSessionDuration } from '../src/sessions/model';
import { makeData, entity, hass } from './fixtures';
import type { Entity } from '../src/shared/types';

const now = Date.parse('2026-09-09T12:00:00Z');
const config = { type: 'custom:growatt-thor-card' };
const idleCommand = { issuedAt: 0, sending: false };
const sensor = (state: string, unit?: string): Entity => ({
  entity_id: 'sensor.test',
  state,
  attributes: { unit_of_measurement: unit },
});

test('View model derives gauge, phase and active-session display without mutating HA', () => {
  const data = makeData();
  const before = JSON.stringify(data);
  const view = buildCardViewModel(hass, config, entity('charging', data), data, now, idleCommand);
  assert.equal(view.kw, 8.3);
  assert.equal(view.maxPower, 11);
  assert.equal(view.animate, true);
  assert.equal(view.active, 3);
  assert.equal(view.complete, true);
  assert.equal(view.sessionActive, true);
  assert.equal(view.energy, 12.4);
  assert.equal(view.duration, '02:00');
  assert.equal(JSON.stringify(data), before);
});
test('Offline and unavailable suppress live readings, but preserve meaningful stop policy', () => {
  const data = makeData();
  for (const connected of [true, false]) {
    const view = buildCardViewModel(
      { ...hass, connected },
      config,
      entity('unavailable', data),
      data,
      now,
      idleCommand,
    );
    assert.equal(view.inactive, true);
    assert.equal(view.kw, null);
    assert.equal(view.animate, false);
    assert.deepEqual(view.currents, [null, null, null]);
    assert.equal(view.caps.limit, false);
    assert.equal(view.caps.start, false);
    assert.equal(view.caps.stop, connected);
  }
});
test('Stale charging is not standby; preparing without telemetry is standby', () => {
  const data = makeData({ meter_received_at: null });
  const charging = buildCardViewModel(hass, config, entity('charging'), data, now, idleCommand);
  assert.equal(charging.kw, null);
  assert.equal(charging.resting, false);
  const ready = { ...data, transaction_active: false };
  assert.equal(
    buildCardViewModel(hass, config, entity('preparing'), ready, now, idleCommand).resting,
    true,
  );
});
test('PV standby treats missing OCPP telemetry as an expected pause', () => {
  const data = makeData({
    meter_received_at: null,
    transaction_active: true,
    working_mode: 'pv_linkage_plus',
  });
  const view = buildCardViewModel(
    hass,
    config,
    entity('suspended_evse', data),
    data,
    now,
    idleCommand,
  );

  assert.equal(view.status.key, 'pv_standby');
  assert.equal(view.fresh, false);
  assert.equal(view.expectedTelemetryPause, true);
  assert.equal(view.resting, true);
  assert.equal(view.kw, null);

  const unhealthy = buildCardViewModel(
    hass,
    config,
    entity('suspended_evse', data),
    { ...data, external_meter_health: 'stale' },
    now,
    idleCommand,
  );
  assert.equal(unhealthy.expectedTelemetryPause, true);
  assert.equal(unhealthy.meterWarning, true);
});
test('Plugged-in PV ChargeWait shows readiness before a transaction has started', () => {
  const data = makeData({
    working_mode: 'pv_linkage_plus',
    auth_mode: 'plug_and_charge',
    status_info: 'ChargeWait',
    transaction_active: false,
    power_w: null,
    sample_at: null,
    meter_received_at: null,
  });
  const view = buildCardViewModel(
    { ...hass, language: 'de' },
    config,
    entity('preparing', data),
    data,
    now,
    idleCommand,
  );
  assert.equal(view.status.key, 'pv_standby');
  assert.equal(view.status.icon, 'mdi:weather-partly-cloudy');
  assert.equal(view.t(view.status.key), 'Wartet auf Ladefreigabe');
  assert.equal(view.expectedTelemetryPause, true);
  assert.equal(view.kw, null);
  assert.equal(view.animate, false);
  // A waiting state must neither invent a meter reading nor enable a Stop.
  assert.equal(view.caps.stop, false);

  for (const state of ['available', 'charging', 'faulted', 'unavailable']) {
    const other = buildCardViewModel(hass, config, entity(state, data), data, now, idleCommand);
    assert.equal(other.expectedTelemetryPause, false, state);
  }
});
test('Reported suspensions show a pause with unknown readings, not a telemetry failure', () => {
  for (const status of ['suspended_ev', 'suspended_evse']) {
    const data = makeData({ meter_received_at: null });
    const view = buildCardViewModel(hass, config, entity(status, data), data, now, idleCommand);
    assert.equal(view.expectedTelemetryPause, true);
    assert.equal(view.resting, true);
    assert.equal(view.kw, null);
    assert.equal(view.animate, false);
    assert.deepEqual(view.currents, [null, null, null]);
    const offline = buildCardViewModel(
      { ...hass, connected: false },
      config,
      entity(status, data),
      data,
      now,
      idleCommand,
    );
    assert.equal(offline.expectedTelemetryPause, false);
  }
});
test('Suspension invalidates the previous charging load but preserves subsequent measurements', () => {
  const data = makeData();
  const target = { ...entity('suspended_ev', data), last_changed: '2026-09-09T11:59:56Z' };
  const paused = buildCardViewModel(hass, config, target, data, now, idleCommand);
  assert.equal(paused.kw, null);
  assert.equal(paused.expectedTelemetryPause, true);
  const fresh = {
    ...data,
    sample_at: '2026-09-09T11:59:58Z',
    meter_received_at: '2026-09-09T11:59:59Z',
    power_w: 0,
  };
  const measured = buildCardViewModel(hass, config, target, fresh, now, idleCommand);
  assert.equal(measured.kw, 0);
  assert.equal(measured.expectedTelemetryPause, false);
});
test('Local command grace protects the display until backend state arrives', () => {
  const data = makeData({ transaction_active: false });
  const target = entity('preparing', data);
  assert.equal(buildCardViewModel(hass, config, target, data, now, idleCommand).caps.start, true);
  assert.equal(
    buildCardViewModel(hass, config, target, data, now, { issuedAt: now - 2000, sending: false })
      .caps.start,
    false,
  );
  assert.equal(
    buildCardViewModel(hass, config, target, data, now, { issuedAt: now - 11000, sending: false })
      .caps.start,
    true,
  );
});
test('Historic session values use the stored units and cost, never current live values', () => {
  const data = makeData({
    transaction_active: false,
    entities: {
      last_session_energy: 'energy',
      last_session_duration: 'duration',
      last_session_cost: 'cost',
    },
  });
  const stored = {
    ...hass,
    states: {
      energy: sensor('9.5', 'kWh'),
      duration: sensor('90', 'min'),
      cost: sensor('2.19', 'EUR'),
    },
  };
  assert.deepEqual(sessionDisplay(stored, data, now), {
    sessionActive: false,
    energy: 9.5,
    duration: '01:30',
    cost: 2.19,
    currency: 'EUR',
  });
  assert.equal(storedSessionDuration(sensor('1.5', 'h')), '01:30');
  assert.equal(storedSessionDuration(sensor('0', 'h')), '00:00');
  assert.equal(storedSessionDuration(sensor('27.5', 'h')), '27:30');
});
test('Unknown session sensors stay missing instead of becoming synthetic zero', () => {
  for (const value of ['unknown', 'unavailable', '', 'NaN', '-1']) {
    assert.equal(entityNumber(sensor(value)), null);
    assert.equal(storedSessionDuration(sensor(value)), '—');
  }
  assert.equal(entityNumber(undefined), null);
  assert.equal(entityNumber(sensor('0')), 0);
});
