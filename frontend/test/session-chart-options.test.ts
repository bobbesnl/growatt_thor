import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildSessionChartOption,
  buildSessionEventMarkLine,
  type SessionChartModel,
} from '../src/sessions/chart-options';
import { chartPalette } from '../src/shared/palette';
import { bindSessionChartEvents } from '../src/sessions/chart-host';

function fixture(): SessionChartModel {
  return {
    points: [
      [1000, 0],
      [2000, 7.2],
    ],
    measuredCurrents: [[2000, 31]],
    configuredCurrents: [[1000, 32]],
    pvSurplus: [
      [1000, 8],
      [1500, null],
      [2000, 9],
    ],
    houseLoad: [[1000, 0.7]],
    batteryFlow: [[1000, -2]],
    markers: [
      {
        at: 1000,
        events: [
          {
            type: 'transaction_started',
            at: '1970-01-01T00:00:01Z',
            source: 'ocpp',
            certainty: 'observed',
          },
        ],
        tone: 'lime',
        provisional: false,
      },
    ],
    eventHost: 'power',
    eventLayerVisible: true,
    reducedMotion: false,
    fadeEventLabels: true,
    dark: false,
    compact: false,
    language: 'en',
    timeZone: 'Europe/Berlin',
    chartSpansDays: false,
    powerAxisVisible: true,
    currentAxisVisible: true,
    extent: [0, 3000],
    chartBreaks: [],
    legendSelected: { Battery: false },
    zoomRange: { start: 17, end: 83 },
    powerSeriesName: 'Power',
    pvSurplusSeriesName: 'PV',
    houseLoadSeriesName: 'House',
    batteryFlowSeriesName: 'Battery',
    configuredCurrentSeriesName: 'Limit',
    measuredCurrentSeriesName: 'Current',
    eventSeriesName: 'Events',
  };
}

test('chart building preserves gaps, signs, units, smoothing and hidden point markers', () => {
  const model = fixture();
  const original = JSON.stringify(model);
  const option = buildSessionChartOption(model, chartPalette(false), 900);
  assert.deepEqual(
    option.series.map((series) => series.showSymbol),
    [false, false, false, false, false, false, undefined],
  );
  assert.deepEqual(
    option.series.slice(0, 6).map((series) => series.smooth),
    [0.25, 0.22, 0.18, 0.18, 0.2, false],
  );
  assert.deepEqual(option.series[1].data, model.pvSurplus);
  assert.deepEqual(option.series[3].data, [[1000, -2]]);
  assert.equal(option.series[4].yAxisIndex, 1);
  assert.equal(option.series[5].step, 'end');
  assert.equal(option.dataZoom[0].start, 17);
  assert.equal(option.dataZoom[1].end, 83);
  assert.equal(option.xAxis.min, 0);
  assert.equal(option.xAxis.max, 3000);
  assert.equal(JSON.stringify(model), original);
});

test('event labels retain fade state and mobile and reduced-motion behavior', () => {
  const model = fixture();
  const option = buildSessionChartOption(model, chartPalette(false), 900);
  assert.equal(option.series[0].markLine?.data[0].label.opacity, 0);
  assert.equal(buildSessionEventMarkLine(model, 1)?.data[0].label.opacity, 1);
  assert.equal(option.series[1].markLine, undefined);
  const mobile = { ...model, compact: true, eventLayerVisible: false, reducedMotion: true };
  const compact = buildSessionChartOption(mobile, chartPalette(true), 390);
  assert.equal(compact.animation, false);
  assert.equal(compact.grid.top, 24);
  assert.equal(compact.series[0].markLine, undefined);
  assert.equal(compact.legend.data.includes('Events'), false);
  assert.ok(compact.xAxis.splitNumber < option.xAxis.splitNumber);
});

test('event adapter handles direct and batched zoom without accepting incomplete ranges', () => {
  const events = new Map<string, (event: unknown) => void>();
  const zooms: unknown[] = [],
    legends: unknown[] = [],
    breaks: unknown[] = [];
  bindSessionChartEvents(
    {
      on(name, callback) {
        events.set(name, callback);
      },
    },
    {
      zoom: (range) => zooms.push(range),
      legend: (selected) => legends.push(selected),
      axisBreak: (key, expanded) => breaks.push([key, expanded]),
    },
  );
  events.get('datazoom')!({ start: 10, end: 80 });
  events.get('datazoom')!({ batch: [{ start: 20, end: 90 }] });
  events.get('datazoom')!({ start: 20 });
  events.get('datazoom')!({ start: NaN, end: 90 });
  events.get('legendselectchanged')!({ selected: { Power: false, PV: true } });
  events.get('axisbreakchanged')!({ breaks: [{ start: 1000, end: 2000, isExpanded: true }] });
  assert.deepEqual(zooms, [
    { start: 10, end: 80 },
    { start: 20, end: 90 },
  ]);
  assert.deepEqual(legends, [{ Power: false, PV: true }]);
  assert.deepEqual(breaks, [['1000:2000', true]]);
});
