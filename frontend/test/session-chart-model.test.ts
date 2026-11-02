import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { deriveSessionChartModel } from '../src/sessions/chart-model';
import { buildSessionChartOption, SESSION_COMPACT_WIDTH_PX } from '../src/sessions/chart-options';
import { chartPalette } from '../src/shared/palette';
import { sessionChartCases } from './session-card-fixtures';

// Captured from the original card's drawChart before moving its calculation.
const contracts: Record<string, string> = JSON.parse(
  readFileSync(new URL('./fixtures/session-chart-contract.json', import.meta.url), 'utf8'),
);
function hash(value: unknown): string {
  return createHash('sha256')
    .update(
      JSON.stringify(value, (_, item: unknown) =>
        typeof item === 'function' ? [item(0), item(Date.parse('2026-10-30T23:00:00Z'))] : item,
      ),
    )
    .digest('hex');
}

test('derived options and fade transitions retain the pre-extraction chart contracts', () => {
  for (const fixture of sessionChartCases()) {
    let eventLabelFadeKey: string | undefined;
    const options: unknown[] = [];
    const before = JSON.stringify(fixture);
    for (let draw = 0; draw < 2; draw++) {
      const derived = deriveSessionChartModel(fixture.session, {
        ...fixture,
        compact: fixture.width <= SESSION_COMPACT_WIDTH_PX,
        zoomRange: { start: 17, end: 83 },
        previousEventLabelFadeKey: eventLabelFadeKey,
      });
      if (derived) {
        eventLabelFadeKey = derived.eventLabelFadeKey;
        options.push(
          buildSessionChartOption(derived.model, chartPalette(fixture.dark), fixture.width),
        );
      } else options.push('clear');
    }
    assert.equal(hash({ options, eventLabelFadeKey }), contracts[fixture.name], fixture.name);
    assert.equal(JSON.stringify(fixture), before, `${fixture.name}: input mutated`);
  }
});

function inputs() {
  const fixture = sessionChartCases()[0];
  return { ...fixture, compact: false, zoomRange: { start: 17, end: 83 } };
}

test('axis visibility and marker host follow visible measured series in priority order', () => {
  const fixture = sessionChartCases().find((item) => item.name === 'hidden-4')!;
  const derived = deriveSessionChartModel(fixture.session, {
    ...inputs(),
    ...fixture,
    compact: false,
  })!;
  assert.equal(derived.model.powerAxisVisible, false);
  assert.equal(derived.model.currentAxisVisible, true);
  assert.equal(derived.model.eventHost, 'measured-current');
  const hidden = sessionChartCases().find((item) => item.name === 'hidden-7')!;
  const none = deriveSessionChartModel(hidden.session, { ...inputs(), ...hidden, compact: false })!;
  assert.equal(none.model.eventHost, 'events');
  assert.equal(none.model.powerAxisVisible, false);
  assert.equal(none.model.currentAxisVisible, false);
  assert.equal(none.model.eventLayerVisible, false);
  assert.equal(none.eventLabelFadeKey, undefined);
});

test('chart derivation retains signed battery flow, unit conversion and unknown intervals', () => {
  const fixture = inputs();
  const model = deriveSessionChartModel(fixture.session, fixture)!.model;
  assert.equal(model.pvSurplus[0][1], 8);
  assert.equal(model.houseLoad[0][1], 1);
  assert.equal(model.batteryFlow[0][1], -2);
  assert.equal(model.batteryFlow[1][1], null);
  assert.equal(model.measuredCurrents[1][1], null);
  assert.deepEqual(model.zoomRange, { start: 17, end: 83 });
  const empty = sessionChartCases().find((item) => item.name === 'events-only')!;
  assert.equal(deriveSessionChartModel(empty.session, fixture), undefined);
  assert.equal(deriveSessionChartModel(undefined, fixture), undefined);
});

test('event-label fade is derived without mutating previous state and respects accessibility', () => {
  const fixture = inputs();
  const first = deriveSessionChartModel(fixture.session, fixture)!;
  assert.equal(first.model.fadeEventLabels, true);
  const repeated = deriveSessionChartModel(fixture.session, {
    ...fixture,
    previousEventLabelFadeKey: first.eventLabelFadeKey,
  })!;
  assert.equal(repeated.model.fadeEventLabels, false);
  assert.equal(repeated.eventLabelFadeKey, first.eventLabelFadeKey);
  for (const extra of [{ compact: true }, { reducedMotion: true }]) {
    const result = deriveSessionChartModel(fixture.session, { ...fixture, ...extra })!;
    assert.equal(result.model.fadeEventLabels, false);
  }
});

test('day boundaries and expanded breaks use the full session in its configured timezone', () => {
  const fixture = inputs();
  assert.equal(
    deriveSessionChartModel(fixture.session, { ...fixture, timeZone: 'UTC' })!.model.chartSpansDays,
    false,
  );
  assert.equal(
    deriveSessionChartModel(fixture.session, { ...fixture, timeZone: 'Europe/Berlin' })!.model
      .chartSpansDays,
    true,
  );
  const long = sessionChartCases().find((item) => item.name === 'long-break')!;
  const collapsed = deriveSessionChartModel(long.session, { ...fixture, ...long })!;
  const axisBreak = collapsed.model.chartBreaks[0];
  const key = `${axisBreak.start}:${axisBreak.end}`;
  const expandedBreaks = new Set([key]);
  const expanded = deriveSessionChartModel(long.session, { ...fixture, ...long, expandedBreaks })!;
  assert.equal(expanded.model.chartBreaks[0].isExpanded, true);
  assert.deepEqual([...expandedBreaks], [key]);
});
