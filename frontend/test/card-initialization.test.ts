import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cardInitialization } from '../src/shared/card-initialization';
import { entity, hass, makeData } from './fixtures';
import type { CardConfig, Hass } from '../src/shared/types';

const auto: CardConfig = { type: 'custom:growatt-thor-card' };
const configured = { ...auto, entry_id: 'one' };
const history = {
  schema: 1,
  items: [],
  total_energy_kwh: 0,
  total_green_energy_kwh: null,
  total_cost: 0,
  total_count: 0,
};
const ready: Hass = {
  ...hass,
  states: { 'sensor.renamed': entity('charging', makeData({ sessions: history })) },
};

test('Initial connection and restored entities do not ask users to reconfigure cards', () => {
  assert.equal(cardInitialization(undefined, configured), 'connecting');
  assert.equal(cardInitialization({ ...hass, states: {} }, configured), 'connecting');
  assert.equal(cardInitialization({ ...hass, connected: false }, configured), 'connecting');
  for (const config of [auto, configured, { ...auto, entity: 'sensor.renamed' }]) {
    assert.equal(cardInitialization(hass, config), 'waiting');
    const restored = {
      ...hass,
      states: {
        'sensor.renamed': {
          entity_id: 'sensor.renamed',
          state: 'unavailable',
          attributes: { restored: true },
        },
      },
    };
    assert.equal(cardInitialization(restored, config), 'waiting');
    assert.equal(cardInitialization(restored, config, true), 'waiting');
    assert.equal(cardInitialization(ready, config), 'ready');
    assert.equal(cardInitialization(ready, config, true), 'ready');
  }
});

test('History can still be loading after live charging data becomes available', () => {
  const liveOnly = { ...hass, states: { 'sensor.renamed': entity('charging') } };
  assert.equal(cardInitialization(liveOnly, configured), 'ready');
  assert.equal(cardInitialization(liveOnly, configured, true), 'waiting');
  assert.equal(cardInitialization(ready, configured, true), 'ready');
});

test('Known data stays visible during connection loss', () => {
  const disconnected = { ...ready, connected: false };
  assert.equal(cardInitialization(disconnected, configured), 'ready');
  assert.equal(cardInitialization(disconnected, configured, true), 'ready');
});

test('Multiple wallboxes need a selection only when none is configured', () => {
  const multiple = {
    ...ready,
    states: {
      ...ready.states,
      'sensor.second': {
        ...entity('charging', makeData({ entry_id: 'two' })),
        entity_id: 'sensor.second',
      },
    },
  };
  assert.equal(cardInitialization(multiple, auto), 'select');
  assert.equal(cardInitialization(multiple, configured), 'ready');
});

test('Unsupported data contracts produce a compatibility hint instead of endless loading', () => {
  const unsupported = {
    ...hass,
    states: { 'sensor.renamed': entity('charging', makeData({ schema: 2 })) },
  };
  assert.equal(cardInitialization(unsupported, configured), 'incompatible');
  assert.equal(
    cardInitialization(unsupported, { ...auto, entity: 'sensor.renamed' }),
    'incompatible',
  );
  const unsupportedHistory = {
    ...hass,
    states: {
      'sensor.renamed': entity('charging', makeData({ sessions: { ...history, schema: 2 } })),
    },
  };
  assert.equal(cardInitialization(unsupportedHistory, configured, true), 'incompatible');
});
