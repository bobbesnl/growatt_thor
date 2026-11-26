/** Callbacks and transient feedback the card template receives from the card element. */
import type { GoalKind, GoalRecurrence } from '../targets/model';
import type { PvLinkageData } from '../shared/types';

export interface CardActions {
  command(action: 'start' | 'stop'): Promise<void>;
  moreInfo(entity?: string): void;
  openGoalPreview(): void;
  setGoal(
    kind: GoalKind,
    value: number,
    startAt?: string,
    recurrence?: GoalRecurrence,
    replaceId?: string,
  ): Promise<void>;
  cancelGoal(requestId: string): Promise<void>;
  openAuth(entity?: string): void;
  openPv(entity: string, data?: PvLinkageData): void;
}
export interface CardFeedback {
  error: string;
  sending: boolean;
}
