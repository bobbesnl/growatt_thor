export type GoalKind = 'energy' | 'duration' | 'budget';
export type GoalStart = 'now' | 'later';
export type GoalRecurrence = 'once' | 'daily';
export interface GoalDefinition {
  kind: GoalKind;
  value: number;
  start: GoalStart;
  at: string;
  recurrence: GoalRecurrence;
  currency: string;
}
/** Injected only by the local simulator. Never a charger service or persisted config. */
export interface GoalSimulation {
  initial?: GoalDefinition;
  save(goal: GoalDefinition): void;
}
export const GOAL_KINDS: readonly GoalKind[] = ['energy', 'duration', 'budget'];
export const GOAL_STARTS: readonly GoalStart[] = ['now', 'later'];
export const GOAL_ICONS: Record<GoalKind, string> = {
  energy: 'mdi:lightning-bolt',
  duration: 'mdi:timer-outline',
  budget: 'mdi:cash-multiple',
};
export function createGoalExampleValues(): Record<GoalKind, string> {
  return { energy: '20', duration: '60', budget: '10' };
}
export function goalValue(value: string, kind: GoalKind): number | null {
  const normalized = value.trim().replace(',', '.');
  if (!/^\d+(?:\.\d+)?$/.test(normalized)) return null;
  const number = Number(normalized);
  return Number.isFinite(number) && number > 0 && (kind !== 'duration' || Number.isInteger(number))
    ? number
    : null;
}
export function localDateTime(date = new Date()): string {
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
export function nextMinuteDateTime(now = new Date()): string {
  const next = new Date(now);
  next.setSeconds(0, 0);
  next.setMinutes(next.getMinutes() + 1);
  return localDateTime(next);
}
export function futureStart(value: string, now = Date.now()): boolean {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return false;
  const date = new Date(value);
  return Number.isFinite(date.getTime()) && date.getTime() > now && localDateTime(date) === value;
}
