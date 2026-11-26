import assert from 'node:assert/strict';
import { test } from 'node:test';
import { sessionGreenTotalView } from '../src/sessions/metrics.template';
import type { SessionHistoryData } from '../src/shared/types';

const history: SessionHistoryData = {
  schema: 1,
  items: [],
  total_energy_kwh: 10,
  total_green_energy_kwh: 6,
  total_green_partial: true,
  total_cost: 1,
  total_count: 1,
};

test('all-history partial green total displays a lower bound with an explanation', () => {
  const view = sessionGreenTotalView(history, 'de');
  assert.match(view.text, /^≥ 6(?:,0+)? kWh$/);
  assert.match(view.title, /Solaranteil/);
  assert.match(view.title, /unbekannter Herkunft/);
  assert.deepEqual(sessionGreenTotalView({ ...history, items: [] }, 'de'), view);
});

test('complete, legacy and zero totals retain exact number formatting', () => {
  for (const partial of [false, undefined]) {
    const view = sessionGreenTotalView({ ...history, total_green_partial: partial }, 'en');
    assert.ok(!view.text.includes('≥'));
    assert.equal(view.title, '');
  }
  const zero = sessionGreenTotalView({ ...history, total_green_energy_kwh: 0 }, 'en');
  assert.match(zero.text, /^≥ 0(?:\.0+)? kWh$/);
});

test('missing or invalid totals stay unknown instead of becoming green zero', () => {
  for (const value of [null, NaN, Infinity, -1]) {
    const view = sessionGreenTotalView({ ...history, total_green_energy_kwh: value }, 'en');
    assert.equal(view.text, '— kWh');
    assert.equal(view.title, '');
  }
});
