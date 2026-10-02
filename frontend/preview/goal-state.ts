import { localDateTime, type GoalDefinition, type GoalKind } from '../src/targets/model';

export type GoalState = 'planned' | 'active' | 'reached' | 'cancelled';
export interface SimulatedGoal extends GoalDefinition {
  state: GoalState;
  delivered: number;
}
export function exampleGoal(kind: GoalKind, state: GoalState, now = Date.now()): SimulatedGoal {
  const value = { energy: 20, duration: 120, budget: 10 }[kind];
  const delivered = { energy: 12.4, duration: 75, budget: 6.2 }[kind];
  return {
    kind,
    value,
    currency: 'EUR',
    state,
    start: state === 'planned' ? 'later' : 'now',
    at: state === 'planned' ? localDateTime(new Date(now + 3600000)) : '',
    recurrence: 'once',
    delivered: state === 'planned' ? 0 : state === 'reached' ? value : delivered,
  };
}
export function applyGoal(definition: GoalDefinition, previous?: SimulatedGoal): SimulatedGoal {
  // Editing an active goal retains its simulated session progress, never real telemetry.
  const delivered =
    definition.start === 'now' && previous?.state === 'active' && previous.kind === definition.kind
      ? previous.delivered
      : 0;
  const state =
    definition.start === 'later' ? 'planned' : delivered >= definition.value ? 'reached' : 'active';
  return { ...definition, delivered, state };
}
export function cancelGoal(goal: SimulatedGoal): SimulatedGoal {
  return ['planned', 'active'].includes(goal.state) ? { ...goal, state: 'cancelled' } : goal;
}
export function goalProgress(goal: SimulatedGoal) {
  return {
    percent: Math.min(100, Math.max(0, (goal.delivered / goal.value) * 100)),
    remaining: Math.max(0, goal.value - goal.delivered),
  };
}
