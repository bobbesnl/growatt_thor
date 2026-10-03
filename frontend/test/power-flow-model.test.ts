import { test } from 'node:test';
import assert from 'node:assert/strict';
import { powerFlowView } from '../src/energy/model';
import { makeData } from './fixtures';

const now = Date.parse('2026-09-09T12:00:00Z');

test('Grid balance uses positive import and negative export semantics', () => {
  const exported = powerFlowView(makeData(), 8.3, 11, true, now);
  assert.equal(exported.direction, 'export');
  assert.equal(exported.valueKw, 1.2);

  const imported = powerFlowView(
    makeData({ power_flow: { ...makeData().power_flow!, grid_w: 800 } }),
    8.3,
    11,
    true,
    now,
  );
  assert.equal(imported.direction, 'import');
  assert.equal(imported.valueKw, 0.8);

  const balanced = powerFlowView(
    makeData({ power_flow: { ...makeData().power_flow!, grid_w: 25 } }),
    8.3,
    11,
    true,
    now,
  );
  assert.equal(balanced.direction, 'balanced');
});

test('PV Linkage+ marks the dynamic zero-grid point', () => {
  const flow = powerFlowView(makeData({ working_mode: 'pv_linkage_plus' }), 5, 11, true, now);
  assert.equal(flow.target?.label, 'zeroGridPoint');
  assert.equal(flow.target?.kw, 6.2);
  assert.equal(flow.gridImportLimitKw, null);
});

test('PV Linkage adds only its configured grid allowance', () => {
  const flow = powerFlowView(
    makeData({
      working_mode: 'pv_linkage',
      power_flow: { ...makeData().power_flow!, grid_w: 800, grid_import_limit_kw: 2 },
    }),
    5,
    11,
    true,
    now,
  );
  assert.equal(flow.target?.label, 'pvControlPoint');
  assert.equal(flow.target?.kw, 6.2);
  assert.equal(flow.gridImportLimitKw, 2);
  assert.equal(flow.overflow, null);
});

test('PV modes expose only the measured gauge segment above their grid target', () => {
  const warning = powerFlowView(
    makeData({
      working_mode: 'pv_linkage_plus',
      power_flow: { ...makeData().power_flow!, grid_w: 800 },
    }),
    5,
    11,
    true,
    now,
  );
  assert.equal(warning.target?.kw, 4.2);
  assert.equal(warning.overflow?.excessKw, 0.8);
  assert.equal(warning.overflow?.severity, 'warning');
  assert.ok(Math.abs((warning.overflow?.fraction ?? 0) - (0.8 / 11) * 100) < 0.001);

  const critical = powerFlowView(
    makeData({
      working_mode: 'pv_linkage',
      power_flow: { ...makeData().power_flow!, grid_w: 3500, grid_import_limit_kw: 2 },
    }),
    5,
    11,
    true,
    now,
  );
  assert.equal(critical.target?.kw, 3.5);
  assert.equal(critical.overflow?.excessKw, 1.5);
  assert.equal(critical.overflow?.severity, 'critical');
});

test('Optional charger-source allocation segments the existing gauge', () => {
  const flow = powerFlowView(
    makeData({
      power_flow: {
        ...makeData().power_flow!,
        charging_sources: { solar_w: 5000, battery_w: 1800, grid_w: 1500 },
      },
    }),
    8.3,
    11,
    true,
    now,
  );
  assert.deepEqual(
    flow.sources.map(({ source, kw }) => [source, kw]),
    [
      ['solar', 5],
      ['battery', 1.8],
      ['grid', 1.5],
    ],
  );
  assert.ok(
    Math.abs(flow.sources.reduce((sum, source) => sum + source.fraction, 0) - 75.4545) < 0.001,
  );
});

test('Incomplete source allocation labels the remainder unknown and stale data hides it', () => {
  const data = makeData({
    power_flow: {
      ...makeData().power_flow!,
      charging_sources: { solar_w: 5000, battery_w: 1000 },
    },
  });
  const current = powerFlowView(data, 8.3, 11, true, now);
  assert.equal(current.sources.at(-1)?.source, 'unknown');
  assert.equal(current.sourcesUnassigned, false);
  assert.ok(Math.abs((current.sources.at(-1)?.kw ?? 0) - 2.3) < 0.001);

  const stale = powerFlowView(
    {
      ...data,
      power_flow: { ...data.power_flow!, received_at: '2026-09-09T11:58:00Z' },
    },
    8.3,
    11,
    true,
    now,
  );
  assert.deepEqual(stale.sources, []);

  const unhealthy = powerFlowView(
    { ...data, external_meter_health: 'faulted' },
    8.3,
    11,
    true,
    now,
  );
  assert.deepEqual(unhealthy.sources, []);
});

test('Wholly unassigned charging uses the normal gauge with an explanatory hint', () => {
  const data = makeData({
    power_flow: {
      ...makeData().power_flow!,
      charging_sources: { solar_w: 0, battery_w: 0, grid_w: 0, unknown_w: 8300 },
    },
  });
  const current = powerFlowView(data, 8.3, 11, true, now);
  assert.deepEqual(current.sources, []);
  assert.equal(current.sourcesUnassigned, true);
  assert.equal(powerFlowView(data, 0, 11, true, now).sourcesUnassigned, false);
  assert.equal(powerFlowView(data, 8.3, 11, false, now).sourcesUnassigned, false);
});

test('Idle export still yields a possible zero-grid point, capped by the gauge', () => {
  const flow = powerFlowView(
    makeData({
      working_mode: 'pv_linkage_plus',
      transaction_active: false,
      power_flow: { ...makeData().power_flow!, grid_w: -15000 },
    }),
    null,
    11,
    true,
    now,
  );
  assert.equal(flow.target?.kw, 11);
  assert.equal(flow.target?.fraction, 100);
});

test('Missing or unhealthy meter data never creates a target marker', () => {
  for (const data of [
    makeData({
      working_mode: 'pv_linkage_plus',
      power_flow: { ...makeData().power_flow!, grid_w: null },
    }),
    makeData({ working_mode: 'pv_linkage', external_meter_health: 'stale' }),
    makeData({
      working_mode: 'pv_linkage',
      power_flow: { ...makeData().power_flow!, received_at: '2026-09-09T11:58:00Z' },
    }),
  ]) {
    const flow = powerFlowView(data, 5, 11, true, now);
    assert.equal(flow.available, false);
    assert.equal(flow.target, null);
    assert.equal(flow.overflow, null);
    assert.equal(flow.visible, true);
  }
  assert.equal(powerFlowView(makeData(), 5, 11, false, now).visible, false);
});

test('Fast mode can show grid balance without implying a PV target', () => {
  const flow = powerFlowView(makeData({ working_mode: 'fast' }), 5, 11, true, now);
  assert.equal(flow.visible, true);
  assert.equal(flow.target, null);
  assert.deepEqual(flow.sources, []);
});
