import { html, nothing } from 'lit';
import {
  GOAL_KINDS,
  GOAL_STARTS,
  GOAL_ICONS,
  localDateTime,
  type GoalKind,
  type GoalRecurrence,
  type GoalStart,
} from './model';
import type { Translator } from '../shared/strings';
import { canReplace, validLiveTarget, type LiveGoal } from './live';
export interface GoalDialogView {
  kind: GoalKind;
  values: Record<GoalKind, string>;
  start: GoalStart;
  at: string;
  recurrence: GoalRecurrence;
  now: number;
  language: string;
  dark: boolean;
  t: Translator;
  value: number | null;
  validTime: boolean;
  validCurrency: boolean;
  unit: string;
  summary: string;
  simulation: boolean;
  live?: LiveGoal;
  busy: boolean;
  confirmed: boolean;
  feedback: string;
}
export interface GoalDialogActions {
  setKind(kind: GoalKind): void;
  setStart(start: GoalStart): void;
  setAt(value: string): void;
  setRecurrence(value: GoalRecurrence): void;
  setValue(value: string): void;
  close(): void;
  closed(): void;
  save(): void;
  confirm(confirmed: boolean): void;
  cancel(requestId: string): void;
}
function renderGoalKinds(view: GoalDialogView, actions: GoalDialogActions, t: Translator) {
  return html`
    <fieldset>
      <legend>${t('goalType')}</legend>
      <div class="choices">
        ${GOAL_KINDS.map(
          (kind) =>
            html`<label class="choice"
              ><input
                type="radio"
                name="goal-kind"
                .value=${kind}
                .checked=${view.kind === kind}
                @change=${() => {
                  actions.setKind(kind);
                }}
              /><span
                ><ha-icon .icon=${GOAL_ICONS[kind]}></ha-icon>${t(`goalKind_${kind}`)}</span
              ></label
            >`,
        )}
      </div>
    </fieldset>
  `;
}

function renderStartChoices(view: GoalDialogView, actions: GoalDialogActions, t: Translator) {
  return html`
    <fieldset>
      <legend>${t('goalStart')}</legend>
      <div class="choices two">
        ${GOAL_STARTS.map(
          (start) =>
            html`<label class="choice"
              ><input
                type="radio"
                name="goal-start"
                .checked=${view.start === start}
                @change=${() => {
                  actions.setStart(start);
                }}
              /><span>${t(`goalStart_${start}`)}</span></label
            >`,
        )}
      </div>
    </fieldset>
  `;
}

function renderStartTime(
  view: GoalDialogView,
  actions: GoalDialogActions,
  t: Translator,
  validTime: boolean,
) {
  return html`
    ${view.start === 'later'
      ? html`<label class="field-label" for="goal-at">${t('goalAt')}</label
          ><input
            id="goal-at"
            type="datetime-local"
            .value=${view.at}
            min=${localDateTime(new Date(view.now))}
            aria-invalid=${validTime ? 'false' : 'true'}
            aria-describedby="time-help"
            @input=${(event: Event) => {
              actions.setAt((event.target as HTMLInputElement).value);
            }}
          />
          <p id="time-help" class="help ${validTime ? '' : 'error-text'}">
            ${t(validTime ? 'goalLocalTime' : 'goalInvalidTime')}
          </p>
          <label class="recurrence">
            <input
              type="checkbox"
              .checked=${view.recurrence === 'daily'}
              @change=${(event: Event) =>
                actions.setRecurrence(
                  (event.target as HTMLInputElement).checked ? 'daily' : 'once',
                )}
            />
            <span
              ><strong>${t('goalEveryday')}</strong><small>${t('goalEverydayHint')}</small></span
            >
          </label>`
      : nothing}
  `;
}

export function renderGoalDialog(view: GoalDialogView, actions: GoalDialogActions) {
  const { t, value, validTime, validCurrency, unit, summary } = view;
  const later = view.start === 'later';
  const supported = validLiveTarget(view.kind, value);
  const liveAvailable = later
    ? view.recurrence === 'daily'
      ? view.live?.scheduleDailyAvailable
      : view.live?.scheduleOnceAvailable
    : view.live?.available;
  const conflict = !!view.live?.request && !canReplace(view.live.request, view.kind, value ?? 0);
  return html`<dialog
    class="card ${view.dark ? 'dark' : ''}"
    aria-labelledby="goal-title"
    aria-describedby="goal-preview"
    @close=${() => actions.closed()}
    @cancel=${(event: Event) => {
      if (view.busy) event.preventDefault();
    }}
  >
    <div class="dialog-head">
      <div class="title">
        <div class="eyebrow">
          GROWATT · THOR · ${t(view.live ? 'goalLivePilot' : 'goalPreview')}
        </div>
        <h2 id="goal-title">${t('goalTitle')}</h2>
      </div>
      <button class="close" aria-label=${t('goalClose')} @click=${() => actions.close()} autofocus>
        ×
      </button>
    </div>
    <div class="body">
      <p class="preview-note" id="goal-preview">
        ${t(
          view.live
            ? later
              ? view.recurrence === 'daily'
                ? 'goalScheduleDailyWarning'
                : 'goalScheduleWarning'
              : view.kind === 'budget'
                ? 'goalBudgetWarning'
                : 'goalLiveWarning'
            : view.simulation
              ? 'goalSimulationNote'
              : 'goalPreviewNote',
        )}
      </p>
      ${renderGoalKinds(view, actions, t)}
      <div class="value-field">
        <label class="field-label" for="goal-value">${t(`goalValue_${view.kind}`)}</label>
        <div class="value-wrap">
          <input
            id="goal-value"
            inputmode=${view.kind === 'duration' ? 'numeric' : 'decimal'}
            autocomplete="off"
            .value=${view.values[view.kind]}
            aria-invalid=${value === null ? 'true' : 'false'}
            aria-describedby="value-help"
            @input=${(event: Event) => {
              actions.setValue((event.target as HTMLInputElement).value);
            }}
          /><span>${unit}</span>
        </div>
        <p id="value-help" class="help ${value === null || !validCurrency ? 'error-text' : ''}">
          ${!validCurrency
            ? t('goalCurrencyMissing')
            : value === null
              ? t(
                  view.kind === 'duration'
                    ? 'goalInvalidDuration'
                    : view.kind === 'budget'
                      ? 'goalInvalidBudget'
                      : 'goalInvalidValue',
                )
              : t('goalExample')}
        </p>
      </div>
      ${renderStartChoices(view, actions, t)} ${renderStartTime(view, actions, t, validTime)}
      <div class="summary" role="status" aria-live="polite">
        <small>${t('goalSummary')}</small
        ><strong>${value === null || !validCurrency ? t('goalIncomplete') : summary}</strong>
        <p>
          ${view.start === 'now'
            ? t(view.live ? 'goalLiveStartSummary' : 'goalStartNowSummary')
            : validTime
              ? `${t('goalStart')}: ${new Date(view.at).toLocaleString(view.language, { dateStyle: 'medium', timeStyle: 'short' })}${view.recurrence === 'daily' ? ` · ${t('goalEveryday')}` : ''}`
              : t('goalInvalidTime')}
        </p>
      </div>
      <p class="help">${t('goalPvNote')}</p>
      ${view.live
        ? html`
            <p role="status">${t(view.live.status)}</p>
            ${!liveAvailable
              ? html`<p>${t(later ? 'goalScheduleUnavailable' : 'goalLiveUnavailable')}</p>`
              : nothing}
            ${view.kind === 'budget' ? html`<p>${t('goalBudgetEvidence')}</p>` : nothing}
            ${conflict ? html`<p>${t('goalLiveConflict')}</p>` : nothing}
            <label
              ><input
                type="checkbox"
                .checked=${view.confirmed}
                ?disabled=${view.busy}
                @change=${(event: Event) =>
                  actions.confirm((event.target as HTMLInputElement).checked)}
              />
              ${t(
                later
                  ? view.live.request
                    ? 'goalScheduleReplaceConfirm'
                    : 'goalScheduleConfirm'
                  : view.live.request
                    ? 'goalLiveRefreshConfirm'
                    : 'goalLiveConfirm',
              )}</label
            >
            ${view.live.request?.state === 'scheduled'
              ? html`<button
                  class="cancel-schedule"
                  ?disabled=${view.busy}
                  @click=${() => actions.cancel(view.live!.request!.request_id)}
                >
                  ${t('goalScheduleCancel')}
                </button>`
              : nothing}
          `
        : nothing}
      ${view.feedback ? html`<p role="status">${t(view.feedback)}</p>` : nothing}
      <div class="dialog-actions">
        <button
          class=${view.simulation || view.live ? 'done' : 'unwired'}
          ?disabled=${view.live
            ? view.busy || !liveAvailable || !supported || conflict || !view.confirmed
            : !view.simulation || value === null || !validTime || !validCurrency}
          @click=${() => actions.save()}
          aria-describedby="goal-preview"
        >
          ${t(
            view.live
              ? later
                ? view.recurrence === 'daily'
                  ? 'goalScheduleDailySet'
                  : 'goalScheduleSet'
                : 'goalLiveSet'
              : view.simulation
                ? 'goalSimulate'
                : 'goalNotConnected',
          )}</button
        ><button class="done" @click=${() => actions.close()}>${t('goalClose')}</button>
      </div>
    </div>
  </dialog>`;
}
