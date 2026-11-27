import type { CardData, PvLinkageData } from '../shared/types';

const MODE_READBACK_TIMEOUT_MS = 60_000;
const APPLY_RESULT_VISIBLE_MS = 180_000;
const applyResultKeys = {
  failed: 'pvApplyFailed',
  partial: 'pvApplyPartial',
  uncertain: 'pvApplyUncertain',
  skipped: 'pvApplyUnsent',
  expired: 'pvApplyUnsent',
} as const;

export function pvProfileFeedback(data: CardData | undefined, now: number) {
  const apply = data?.pv_linkage?.profile_apply;
  if (!apply) return null;
  const { status, completed_steps: done, total_steps: total } = apply;
  if (status === 'queued') return { key: 'pvApplyQueued', busy: true, tone: 'warning' };
  if (status === 'applying') return { key: 'pvApplying', busy: true, tone: 'warning', done, total };

  const elapsed = now - Date.parse(apply.updated_at);
  if (elapsed >= APPLY_RESULT_VISIBLE_MS) return null;
  if (status === 'success')
    return data?.working_mode === apply.working_mode
      ? { key: 'pvApplyConfirmed', busy: false, tone: 'success' }
      : null;
  if (status === 'awaiting_mode') {
    return elapsed < MODE_READBACK_TIMEOUT_MS
      ? { key: 'pvApplyAwaitingMode', busy: true, tone: 'warning' }
      : { key: 'pvApplyModeUnconfirmed', busy: false, tone: 'warning' };
  }
  return { key: applyResultKeys[status], busy: false, tone: 'error', done, total };
}
export type PvProfileFeedback = NonNullable<ReturnType<typeof pvProfileFeedback>>;

export type PvMode = 'pv_linkage' | 'pv_linkage_plus';
export type PvBoost = 'disabled' | 'manual' | 'smart';
export interface PvLinkageDraft {
  workingMode: PvMode;
  gridImportLimitKw: string;
  boostMode: PvBoost;
  manualStart: string;
  manualEnd: string;
  smartFinish: string;
  smartTargetEnergyKwh: string;
}

export function initialPvDraft(data: PvLinkageData): PvLinkageDraft {
  return {
    workingMode: data.working_mode,
    gridImportLimitKw: String(data.grid_import_limit_kw ?? 0),
    boostMode: data.boost_mode,
    manualStart: data.manual_start || '00:00',
    manualEnd: data.manual_end || '23:59',
    smartFinish: data.smart_finish || '07:00',
    smartTargetEnergyKwh: String(data.smart_target_energy_kwh ?? 10),
  };
}

const validTime = (value: string) => /^([01]\d|2[0-3]):[0-5]\d$/.test(value);

export function pvDraftErrors(draft: PvLinkageDraft): string[] {
  const errors: string[] = [];
  const grid = Number(draft.gridImportLimitKw);
  if (
    draft.workingMode === 'pv_linkage' &&
    (!Number.isFinite(grid) ||
      grid < 0 ||
      grid > 22 ||
      Math.abs(grid * 10 - Math.round(grid * 10)) > 1e-7)
  )
    errors.push('pvInvalidGrid');
  if (
    draft.boostMode === 'manual' &&
    (!validTime(draft.manualStart) || !validTime(draft.manualEnd))
  )
    errors.push('pvInvalidTime');
  const energy = Number(draft.smartTargetEnergyKwh);
  if (
    draft.boostMode === 'smart' &&
    (!validTime(draft.smartFinish) ||
      !Number.isFinite(energy) ||
      energy < 0.1 ||
      energy > 200 ||
      Math.abs(energy * 10 - Math.round(energy * 10)) > 1e-7)
  )
    errors.push('pvInvalidSmart');
  return errors;
}

export function pvServicePayload(entryId: string, draft: PvLinkageDraft) {
  return {
    entry_id: entryId,
    working_mode: draft.workingMode,
    ...(draft.workingMode === 'pv_linkage'
      ? { grid_import_limit_kw: Number(draft.gridImportLimitKw) }
      : {}),
    boost_mode: draft.boostMode,
    ...(draft.boostMode === 'manual'
      ? { manual_start: draft.manualStart, manual_end: draft.manualEnd }
      : {}),
    ...(draft.boostMode === 'smart'
      ? {
          smart_finish: draft.smartFinish,
          smart_target_energy_kwh: Number(draft.smartTargetEnergyKwh),
        }
      : {}),
  };
}

export function meterLabel(health: string): string {
  return (
    {
      healthy: 'pvMeterCurrent',
      stale: 'pvMeterStale',
      faulted: 'pvMeterFaulted',
      not_reported: 'pvMeterMissing',
    }[health] || 'pvMeterMissing'
  );
}
