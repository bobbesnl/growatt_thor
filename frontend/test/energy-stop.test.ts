import assert from 'node:assert/strict';
import { test } from 'node:test';
import { sessionEventReason } from '../src/sessions/event-model';
import { renderEnergyStop } from '../src/shared/energy-stop';

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

function text(value: unknown): string {
  if (value == null || typeof value !== 'object') return String(value ?? '');
  if (Array.isArray(value)) return value.map(text).join('');
  if ('strings' in value && 'values' in value) {
    const template = value as { strings: string[]; values: unknown[] };
    return template.strings
      .map(
        (part, index) =>
          part + (index < template.values.length ? text(template.values[index]) : ''),
      )
      .join('');
  }
  return '';
}

test('The protection stop time uses the Home Assistant time zone, not the browser one', () => {
  const report = {
    reason: 'battery' as const,
    at: '2026-09-09T11:30:00Z',
    threshold_w: 500,
    hold_seconds: 60,
    observed_w: 800,
  };

  assert.match(text(renderEnergyStop(report, 'de', 'Europe/Berlin')), /09\.09\.26, 13:30/);
  assert.match(text(renderEnergyStop(report, 'de', 'America/New_York')), /09\.09\.26, 07:30/);
});
