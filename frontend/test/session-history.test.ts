import assert from 'node:assert/strict';
import test from 'node:test';
import {
  formatSessionDate,
  formatSessionPeriod,
  formatSessionChartTick,
  formatSessionNumber,
  selectedSession,
  sessionChartBreaks,
  sessionChartExtent,
  sessionChartPoints,
  sessionChartSpansDays,
  sessionEventMarkers,
  sessionNumericPoints,
  sessionSignedChartPoints,
  sessionRows,
  sessionPage,
  sessionAccountingSummary,
  sessionEnergyBreakdown,
  sessionRowMetrics,
} from '../src/sessions/model';
import type { SessionEvent, SessionHistoryData } from '../src/shared/types';

const history: SessionHistoryData = {
  schema: 1,
  total_energy_kwh: 8,
  total_green_energy_kwh: null,
  total_cost: 2,
  total_count: 3,
  items: [
    {
      session_id: 'active',
      active: true,
      start_time: '2026-09-12 08:00:00',
      end_time: null,
      energy_kwh: 1.2,
      green_energy_kwh: null,
      cost: null,
      duration_minutes: null,
      authorized_identifier: 'RFID-LIVE',
      power_curve: [['2026-09-12T08:05:00Z', 7200]],
    },
    {
      session_id: 'a',
      start_time: '2026-09-11 08:00:00',
      end_time: '2026-09-11 09:00:00',
      energy_kwh: 3,
      green_energy_kwh: null,
      cost: 1,
      duration_minutes: 60,
      authorized_identifier: 'RFID-A',
      power_curve: [],
    },
    {
      session_id: 'b',
      start_time: '2026-09-10 12:00:00',
      end_time: null,
      energy_kwh: null,
      green_energy_kwh: null,
      cost: null,
      duration_minutes: null,
      authorized_identifier: null,
      power_curve: [],
    },
    {
      session_id: 'c',
      start_time: '2026-09-11 18:00:00',
      end_time: '2026-09-11 19:00:00',
      energy_kwh: 5,
      green_energy_kwh: null,
      cost: 1,
      duration_minutes: 60,
      authorized_identifier: 'freevenID',
      power_curve: [],
    },
  ],
};

test('Live row metrics advance known solar and grid cost despite incomplete coverage', () => {
  const row = {
    ...history.items[0],
    energy_kwh: 3,
    source_energy_kwh: { direct_solar: 2, direct_grid: 0.5, battery_unknown: 0, unknown: 0.5 },
    effective_grid_cost: 0.15,
  };
  const before = JSON.stringify(row);
  assert.deepEqual(sessionRowMetrics(row), {
    green: 2,
    greenPartial: true,
    unknown: 0.5,
    cost: 0.15,
    costIsGrid: true,
    costPartial: true,
  });
  const next = {
    ...row,
    energy_kwh: 5,
    source_energy_kwh: { ...row.source_energy_kwh, direct_solar: 3, direct_grid: 1.5 },
    effective_grid_cost: 0.45,
  };
  assert.equal(sessionRowMetrics(next).green, 3);
  assert.equal(sessionRowMetrics(next).cost, 0.45);
  assert.equal(JSON.stringify(row), before);
  assert.equal(sessionRowMetrics({ ...next, active: false, cost: 1.23 }).cost, 0.45);
  assert.equal(sessionRowMetrics({ ...next, active: false }).costIsGrid, true);
});

test('Completed accounting never falls back to the charger flat-rate price', () => {
  const row = {
    ...history.items[1],
    energy_kwh: 9.655,
    cost: 2.22,
    source_energy_kwh: {
      direct_solar: 9.521389,
      direct_grid: 0.031605,
      battery_unknown: 0.000006,
      unknown: 0.102,
    },
    effective_grid_cost: null,
  };
  assert.equal(sessionRowMetrics(row).cost, null);
  assert.equal(sessionRowMetrics(row).costIsGrid, true);
  assert.equal(sessionRowMetrics({ ...row, effective_grid_cost: 0.009922 }).cost, 0.009922);
  assert.equal(sessionRowMetrics({ ...row, energy_kwh: 20 }).cost, null);
  assert.equal(sessionRowMetrics({ ...row, source_energy_kwh: null }).cost, 2.22);
  assert.equal(sessionRowMetrics({ ...row, source_energy_kwh: null }).costIsGrid, false);
});

test('Session IDs can be used to find the same item in either layout', () => {
  assert.deepEqual(
    sessionRows(history, 'ACTIVE', 'start', false).map((row) => row.session_id),
    ['active'],
  );
});

test('Row metrics preserve unknown data, valid zero and negative tariffs', () => {
  assert.equal(sessionRowMetrics(history.items[0]).green, null);
  assert.equal(sessionRowMetrics(history.items[0]).cost, null);
  const row = {
    ...history.items[0],
    energy_kwh: 3,
    source_energy_kwh: { direct_solar: 3, direct_grid: 0, battery_unknown: 0, unknown: 0 },
    effective_grid_cost: 0,
  };
  assert.equal(sessionRowMetrics(row).green, 3);
  assert.equal(sessionRowMetrics(row).greenPartial, false);
  assert.equal(sessionRowMetrics(row).cost, 0);
  assert.equal(sessionRowMetrics({ ...row, effective_grid_cost: -0.2 }).cost, -0.2);
  assert.equal(sessionRowMetrics({ ...row, effective_grid_cost: NaN }).cost, null);
  const unknown = {
    ...row,
    source_energy_kwh: { direct_solar: 0, direct_grid: 0, battery_unknown: 0, unknown: 3 },
  };
  assert.equal(sessionRowMetrics(unknown).green, null);
  assert.equal(sessionRowMetrics(unknown).cost, null);
  const invalid = { ...row, energy_kwh: 4 };
  assert.equal(sessionRowMetrics(invalid).green, null);
  assert.equal(sessionRowMetrics(invalid).cost, null);
});

test('session accounting accepts balanced negative-cost data and rejects legacy or malformed rows', () => {
  const row = {
    ...history.items[1],
    source_energy_kwh: { direct_solar: 1, direct_grid: 1, battery_unknown: 0.5, unknown: 0.5 },
    effective_grid_cost: -0.15,
    accounting_coverage: 2.5 / 3,
    accounting_quality: 'derived' as const,
    accounting_policy: { id: 'grid_first', version: 1 },
  };
  assert.equal(sessionAccountingSummary(row)?.cost, -0.15);
  assert.equal(sessionAccountingSummary(history.items[1]), null);
  assert.equal(
    sessionAccountingSummary({
      ...row,
      source_energy_kwh: { ...row.source_energy_kwh, unknown: -1 },
    }),
    null,
  );
  assert.equal(
    sessionAccountingSummary({
      ...row,
      source_energy_kwh: { ...row.source_energy_kwh, unknown: 2 },
    }),
    null,
  );
});

test('filters identifiers and preserves missing values', () => {
  assert.deepEqual(
    sessionRows(history, 'rfid-a', 'start', false).map((row) => row.session_id),
    ['a'],
  );
  assert.equal(
    sessionRows(history, '', 'energy', true).find((row) => row.session_id === 'b')?.energy_kwh,
    null,
  );
  assert.equal(sessionRows(history, '', 'end', true)[0].session_id, 'active');
});

test('pages the filtered and sorted recent rows without losing later entries', () => {
  const sorted = sessionRows(history, '', 'start', false);
  const first = sessionPage(sorted, 0, 2);
  const second = sessionPage(sorted, 1, 2);
  assert.deepEqual(
    first.items.map((row) => row.session_id),
    ['active', 'c'],
  );
  assert.deepEqual(
    second.items.map((row) => row.session_id),
    ['a', 'b'],
  );
  assert.deepEqual([first.from, first.to, first.total, first.count], [1, 2, 4, 2]);
  assert.deepEqual([second.from, second.to], [3, 4]);
  assert.equal(sessionPage(sorted, 99, 2).index, 1);
  assert.deepEqual(
    sessionPage(sessionRows(history, 'rfid-a', 'start', false), 1, 2).items.map(
      (row) => row.session_id,
    ),
    ['a'],
  );
  assert.deepEqual(sessionPage([], 3, 10), {
    items: [],
    index: 0,
    count: 1,
    from: 0,
    to: 0,
    total: 0,
  });
});

test('defaults the chart to latest session and selects another by stable id', () => {
  assert.equal(selectedSession(history.items)?.session_id, 'active');
  assert.equal(selectedSession(history.items)?.active, true);
  assert.equal(selectedSession(history.items, 'c')?.authorized_identifier, 'freevenID');
});

test('formats session table values with no more than two decimal places', () => {
  assert.equal(formatSessionNumber(15.339, 'de'), '15,34');
  assert.equal(formatSessionNumber(3, 'de'), '3');
  assert.equal(formatSessionNumber(null, 'de'), '—');
});

test('formats the selected session timestamp for people instead of exposing ISO syntax', () => {
  assert.equal(formatSessionDate('2026-09-16 10:12:54', 'de'), 'Mi., 16.09.2026, 10:12');
  assert.equal(formatSessionDate('invalid', 'de'), '—');
});

test('adds a localized weekday to chart ticks only when the session spans days', () => {
  const timestamp = new Date('2026-09-16T10:12:54').getTime();
  assert.equal(formatSessionChartTick(timestamp, 'de', false), '10:12');
  assert.equal(formatSessionChartTick(timestamp, 'de', true), 'Mi\n10:12');
});

test('mobile periods share the date only within the same local calendar day', () => {
  assert.deepEqual(formatSessionPeriod('2026-10-02T13:01:05', '2026-10-02T17:32:16', 'en-US'), {
    day: 'Friday, 10/2/2026',
    start: '01:01 PM',
    end: '05:32 PM',
  });
  const overnight = formatSessionPeriod('2026-10-02T23:00:00', '2026-10-03T01:00:00', 'de');
  assert.equal(overnight.day, null);
  assert.equal(overnight.start, 'Fr., 02.10.2026, 23:00');
  assert.equal(overnight.end, 'Sa., 03.10.2026, 01:00');
  assert.deepEqual(formatSessionPeriod('2026-10-02T13:01:05', null, 'de'), {
    day: 'Freitag, 2.10.2026',
    start: '13:01',
    end: '—',
  });
  assert.deepEqual(formatSessionPeriod('invalid', null, 'de'), { day: null, start: '—', end: '—' });
});

test('normalizes chart points and includes event-only boundaries in the time axis', () => {
  const points = sessionChartPoints([
    ['2026-09-12T08:00:00Z', 7200],
    ['invalid', 5000],
    ['2026-09-12T09:00:00Z', -1],
  ]);
  const events: SessionEvent[] = [
    {
      type: 'plugged_in',
      at: '2026-09-12T07:55:00Z',
      source: 'growatt',
      certainty: 'observed',
    },
    {
      type: 'unplugged',
      at: '2026-09-12T09:05:00Z',
      source: 'growatt',
      certainty: 'observed',
    },
  ];
  const markers = sessionEventMarkers(events);
  const extent = sessionChartExtent(points, markers);
  assert.deepEqual(points, [[Date.parse('2026-09-12T08:00:00Z'), 7.2]]);
  assert.ok(extent && extent[0] < markers[0].at && extent[1] > markers[1].at);
});

test('compresses long empty chart intervals but preserves context around their boundaries', () => {
  const points: [number, number][] = [
    [Date.parse('2026-09-12T08:00:00Z'), 7.2],
    [Date.parse('2026-09-12T08:05:00Z'), 0],
  ];
  const markers = sessionEventMarkers([
    {
      type: 'energy_flow_stopped',
      at: '2026-09-12T08:05:00Z',
      source: 'meter',
      certainty: 'derived',
    },
    {
      type: 'transaction_stopped',
      at: '2026-09-14T08:05:00Z',
      source: 'ocpp',
      certainty: 'observed',
    },
  ]);
  assert.deepEqual(sessionChartBreaks(points, markers), [
    {
      start: Date.parse('2026-09-12T08:20:00Z'),
      end: Date.parse('2026-09-14T07:50:00Z'),
    },
  ]);
  assert.equal(sessionChartSpansDays(points, markers), true);
  assert.deepEqual(
    sessionChartBreaks(
      [
        [Date.parse('2026-09-12T08:00:00Z'), 1],
        [Date.parse('2026-09-12T10:00:00Z'), 0],
      ],
      [],
    ),
    [],
  );
});

test('normalizes ampere curves without converting their values', () => {
  assert.deepEqual(
    sessionNumericPoints([
      ['2026-09-12T08:00:00Z', 36],
      ['2026-09-12T08:05:00Z', 30.5],
      ['bad', 16],
    ]),
    [
      [Date.parse('2026-09-12T08:00:00Z'), 36],
      [Date.parse('2026-09-12T08:05:00Z'), 30.5],
    ],
  );
});

test('preserves the battery-flow sign while converting site power to kilowatts', () => {
  assert.deepEqual(
    sessionSignedChartPoints([
      ['2026-09-12T08:00:00Z', -1800],
      ['2026-09-12T08:05:00Z', 2400],
      ['bad', 1000],
    ]),
    [
      [Date.parse('2026-09-12T08:00:00Z'), -1.8],
      [Date.parse('2026-09-12T08:05:00Z'), 2.4],
    ],
  );
});

test('groups simultaneous event markers and preserves provisional state', () => {
  const markers = sessionEventMarkers([
    {
      type: 'transaction_stopped',
      at: '2026-09-12T09:42:00Z',
      source: 'ocpp',
      certainty: 'observed',
      reason: 'EVDisconnected',
    },
    {
      type: 'unplugged',
      at: '2026-09-12T09:42:15Z',
      source: 'growatt',
      certainty: 'observed',
    },
    {
      type: 'charging_paused',
      at: '2026-09-12T09:10:00Z',
      source: 'meter',
      certainty: 'provisional',
    },
  ]);
  assert.equal(markers.length, 2);
  assert.equal(markers[0].tone, 'amber');
  assert.equal(markers[0].provisional, true);
  assert.deepEqual(
    markers[1].events.map((event) => event.type),
    ['transaction_stopped', 'unplugged'],
  );
});

test('Energy strip hides zero sources and does not present unassigned energy as free charging', () => {
  const row = {
    ...history.items[0],
    energy_kwh: 28.23,
    source_energy_kwh: { direct_solar: 0, direct_grid: 0, battery_unknown: 0, unknown: 28.23 },
    effective_grid_cost: 0,
  };
  const view = sessionEnergyBreakdown(row)!;
  assert.deepEqual(
    view.parts.map((p) => p.label),
    ['unknown'],
  );
  assert.equal(view.parts[0].share, 100);
  assert.equal(view.cost, null);
  assert.equal(view.fullyUnknown, true);
  assert.equal(view.coverage, 0);
});
test('Energy strip retains valid zero and negative costs, tiny shares and partial coverage', () => {
  const row = {
    ...history.items[0],
    energy_kwh: 10,
    source_energy_kwh: { direct_solar: 8, direct_grid: 0.01, battery_unknown: 1, unknown: 0.99 },
    effective_grid_cost: -0.2,
  };
  const view = sessionEnergyBreakdown(row)!;
  assert.equal(view.parts.length, 4);
  assert.equal(view.cost, -0.2);
  assert.ok(Math.abs(view.coverage - 90.1) < 1e-8);
  assert.equal(view.parts.find((p) => p.label === 'grid')!.share, 0.1);
  assert.equal(sessionEnergyBreakdown({ ...row, effective_grid_cost: 0 })!.cost, 0);
  assert.equal(sessionEnergyBreakdown({ ...row, effective_grid_cost: NaN })!.cost, null);
  assert.equal(sessionEnergyBreakdown({ ...row, source_energy_kwh: null }), null);
});
test('Energy strip omits floating-point residue and handles empty or invalid totals', () => {
  const row = {
    ...history.items[0],
    energy_kwh: 10,
    source_energy_kwh: { direct_solar: 10, direct_grid: 0, battery_unknown: 0, unknown: 1e-14 },
  };
  assert.deepEqual(
    sessionEnergyBreakdown(row)!.parts.map((p) => p.label),
    ['solar'],
  );
  assert.equal(sessionEnergyBreakdown(row)!.unknown, 0);
  assert.equal(sessionEnergyBreakdown({ ...row, energy_kwh: 20 }), null);
  assert.deepEqual(
    sessionEnergyBreakdown({
      ...row,
      energy_kwh: 0,
      source_energy_kwh: { direct_solar: 0, direct_grid: 0, battery_unknown: 0, unknown: 0 },
    })!.parts,
    [],
  );
});
