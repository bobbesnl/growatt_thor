import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  applyGoal,
  cancelGoal,
  exampleGoal,
  goalProgress,
  type GoalState,
} from '../preview/goal-state';
import { GOAL_KINDS, futureStart } from '../src/targets/model';

test('All goal kinds have planned, active and terminal simulator fixtures', () => {
  const now = Date.now();
  for (const kind of GOAL_KINDS) {
    for (const state of ['planned', 'active', 'reached', 'cancelled'] as GoalState[]) {
      const goal = exampleGoal(kind, state, now);
      assert.equal(goal.kind, kind);
      assert.equal(goal.state, state);
      if (state === 'planned') {
        assert.equal(goal.delivered, 0);
        assert.ok(futureStart(goal.at, now));
        assert.equal(goal.recurrence, 'once');
      }
      if (state === 'active')
        assert.ok(goalProgress(goal).percent > 0 && goalProgress(goal).percent < 100);
      if (state === 'reached') assert.equal(goalProgress(goal).percent, 100);
    }
  }
});
test('Simulator preserves a daily schedule definition', () => {
  const planned = exampleGoal('energy', 'planned');
  const daily = applyGoal({ ...planned, recurrence: 'daily' });
  assert.equal(daily.state, 'planned');
  assert.equal(daily.recurrence, 'daily');
});
test('Editing retains active progress only for the same kind; new and planned targets start at zero', () => {
  const active = exampleGoal('energy', 'active');
  assert.equal(applyGoal({ ...active, value: 30 }, active).delivered, 12.4);
  assert.equal(applyGoal({ ...active, value: 10 }, active).state, 'reached');
  assert.equal(applyGoal({ ...active, kind: 'budget' }, active).delivered, 0);
  assert.equal(applyGoal({ ...active, start: 'later' }, active).state, 'planned');
  assert.equal(applyGoal(active).delivered, 0);
  assert.equal(active.value, 20);
});
test('Cancellation preserves result without mutating inputs; terminal goals stay terminal', () => {
  const active = exampleGoal('budget', 'active');
  const cancelled = cancelGoal(active);
  assert.equal(active.state, 'active');
  assert.equal(cancelled.state, 'cancelled');
  assert.equal(cancelled.delivered, active.delivered);
  assert.equal(cancelGoal(cancelled), cancelled);
  const reached = exampleGoal('duration', 'reached');
  assert.equal(cancelGoal(reached), reached);
  assert.deepEqual(goalProgress({ ...reached, delivered: 150 }), { percent: 100, remaining: 0 });
});
