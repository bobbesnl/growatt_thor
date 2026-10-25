import { browserTimeZone, localDateTimeInZone, localTimeToUtc } from '../shared/time';
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
export function localDateTime(date = new Date(), timeZone = browserTimeZone()): string {
  return localDateTimeInZone(date, timeZone);
}
export function nextMinuteDateTime(now = new Date(), timeZone = browserTimeZone()): string {
  return localDateTime(new Date(Math.floor(now.getTime() / 60000) * 60000 + 60000), timeZone);
}
export function futureStart(
  value: string,
  now = Date.now(),
  timeZone = browserTimeZone(),
): boolean {
  const instant = localTimeToUtc(value, timeZone);
  return instant !== null && Date.parse(instant) > now;
}
