import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  goalValue,
  futureStart,
  localDateTime,
  nextMinuteDateTime,
  createGoalExampleValues,
  GOAL_KINDS,
  GOAL_ICONS,
} from '../src/targets/model';

test('Each dialog reset gets independent example values and complete choice metadata', () => {
  const first = createGoalExampleValues();
  first.energy = '99';
  assert.equal(createGoalExampleValues().energy, '20');
  for (const kind of GOAL_KINDS) {
    assert.ok(GOAL_ICONS[kind]);
    assert.notEqual(goalValue(createGoalExampleValues()[kind], kind), null);
  }
});

test('Preview values accept decimal comma but reject ambiguous or invalid targets', () => {
  assert.equal(goalValue('20,5', 'energy'), 20.5);
  assert.equal(goalValue(' 10.99 ', 'budget'), 10.99);
  assert.equal(goalValue('60', 'duration'), 60);
  assert.equal(goalValue('1.5', 'duration'), null);
  for (const value of ['', '0', '-1', 'NaN', 'Infinity', '1e3', '1,000.5', '1.000,5'])
    assert.equal(goalValue(value, 'energy'), null);
});
test('Start selection is a local future date, not a duration or finish time', () => {
  const now = new Date(2026, 8, 9, 12, 0).getTime();
  assert.equal(futureStart('2026-09-09T13:00', now), true);
  assert.equal(futureStart('2026-09-09T11:00', now), false);
  assert.equal(futureStart('2026-09-09T12:00', now), false);
  assert.equal(futureStart('2026-02-30T12:00', now), false);
  assert.equal(futureStart('', now), false);
  assert.equal(localDateTime(new Date(now)), '2026-09-09T12:00');
  assert.equal(nextMinuteDateTime(new Date(2026, 8, 9, 12, 0, 15)), '2026-09-09T12:01');
});
