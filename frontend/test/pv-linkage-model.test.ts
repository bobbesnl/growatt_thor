import { test } from 'node:test';
import assert from 'node:assert/strict';
import { initialPvDraft, meterLabel, pvDraftErrors, pvServicePayload } from '../src/pv/model';

test('PV dialog initializes from the versioned card contract', () => {
  const draft = initialPvDraft({
    working_mode: 'pv_linkage',
    grid_import_limit_kw: 2.4,
    boost_mode: 'manual',
    manual_start: '10:00',
    manual_end: '12:30',
    smart_finish: null,
    smart_target_energy_kwh: null,
    draft_dirty: false,
    blocked_reason: null,
  });
  assert.equal(draft.gridImportLimitKw, '2.4');
  assert.equal(draft.manualEnd, '12:30');
  assert.deepEqual(pvDraftErrors(draft), []);
});

test('PV dialog rejects invalid mode-dependent input without inventing defaults', () => {
  const regular = initialPvDraft({
    working_mode: 'pv_linkage',
    grid_import_limit_kw: 2.4,
    boost_mode: 'disabled',
    manual_start: null,
    manual_end: null,
    smart_finish: null,
    smart_target_energy_kwh: null,
    draft_dirty: false,
    blocked_reason: null,
  });
  assert.deepEqual(pvDraftErrors({ ...regular, gridImportLimitKw: '2.45' }), ['pvInvalidGrid']);
  assert.deepEqual(
    pvDraftErrors({ ...regular, boostMode: 'manual', manualStart: '', manualEnd: '12:00' }),
    ['pvInvalidTime'],
  );
  assert.deepEqual(
    pvDraftErrors({
      ...regular,
      boostMode: 'smart',
      smartFinish: '07:00',
      smartTargetEnergyKwh: '0',
    }),
    ['pvInvalidSmart'],
  );
});

test('PV service payload contains only fields relevant to the selected behavior', () => {
  const payload = pvServicePayload('entry-one', {
    workingMode: 'pv_linkage_plus',
    gridImportLimitKw: '4.2',
    boostMode: 'smart',
    manualStart: '10:00',
    manualEnd: '12:00',
    smartFinish: '07:30',
    smartTargetEnergyKwh: '12.5',
  });
  assert.deepEqual(payload, {
    entry_id: 'entry-one',
    working_mode: 'pv_linkage_plus',
    boost_mode: 'smart',
    smart_finish: '07:30',
    smart_target_energy_kwh: 12.5,
  });
});

test('Meter states use precise user-facing concepts', () => {
  assert.equal(meterLabel('healthy'), 'pvMeterCurrent');
  assert.equal(meterLabel('stale'), 'pvMeterStale');
  assert.equal(meterLabel('faulted'), 'pvMeterFaulted');
  assert.equal(meterLabel('not_reported'), 'pvMeterMissing');
});
