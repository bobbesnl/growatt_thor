import assert from 'node:assert/strict';
import { test } from 'node:test';
import { sessionEventReason } from '../src/sessions/events.template';

test('Protection stops use localized reasons in chart and mobile timeline', () => {
  assert.equal(sessionEventReason('energy_guard_battery', 'de'), 'Batterieentladung');
  assert.equal(sessionEventReason('energy_guard_grid', 'en'), 'Grid import');
  for (const language of ['en', 'de', 'nl', 'fr', 'es', 'it', 'hu', 'sl']) {
    for (const reason of ['energy_guard_battery', 'energy_guard_grid']) {
      assert(sessionEventReason(reason, language));
      assert.notEqual(sessionEventReason(reason, language), reason);
    }
  }
  assert.equal(sessionEventReason('Remote', 'de'), 'Remote');
});
