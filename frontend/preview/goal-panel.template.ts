import { html, nothing } from 'lit';
import { translate } from '../src/shared/strings';
import { goalProgress, type SimulatedGoal } from './goal-state';

const stateIcons = {
  planned: 'mdi:clock-outline',
  active: 'mdi:target',
  reached: 'mdi:check-circle-outline',
  cancelled: 'mdi:close-circle-outline',
};
export function renderGoalPanel(
  goal: SimulatedGoal | undefined,
  language: string,
  dark: boolean,
  actions: { edit(): Promise<void>; cancel(): void },
) {
  const t = translate(language);
  const format = (value: number) => value.toLocaleString(language, { maximumFractionDigits: 2 });
  const editable = goal && ['planned', 'active'].includes(goal.state);
  const unit = goal?.kind === 'energy' ? 'kWh' : goal?.kind === 'duration' ? 'min' : goal?.currency;
  const progress = goal && goalProgress(goal);
  return html` <section aria-label=${t('goalTitle')} data-state=${goal?.state || 'none'}>
      <div class="head">
        <strong><ha-icon icon="mdi:target"></ha-icon>${t('goalTitle')}</strong>${goal
          ? html`<span class="state"
              ><ha-icon .icon=${stateIcons[goal.state]}></ha-icon>${t(
                `goalState_${goal.state}`,
              )}</span
            >`
          : nothing}
      </div>
      ${goal && progress
        ? html`
            <div class="amount" aria-label=${t(`goalKind_${goal.kind}`)}>
              ${goal.state === 'planned'
                ? html`<strong>${format(goal.value)}</strong> ${unit}`
                : html`<strong>${format(goal.delivered)}</strong
                    ><span>${t('goalOf')} ${format(goal.value)} ${unit}</span>`}
            </div>
            ${goal.state === 'planned'
              ? html`<p>
                  ${t('goalStart')}:
                  ${new Date(goal.at).toLocaleString(language, {
                    dateStyle: 'medium',
                    timeStyle: 'short',
                  })}${goal.recurrence === 'daily' ? ` · ${t('goalEveryday')}` : ''}
                </p>`
              : html` <progress
                    aria-label=${t('goalProgress')}
                    max="100"
                    .value=${progress.percent}
                  ></progress>
                  <p>
                    ${goal.state === 'reached'
                      ? t('goalReachedReason')
                      : goal.state === 'cancelled'
                        ? t('goalCancelledReason')
                        : `${format(progress.remaining)} ${unit} ${t('goalRemaining')}`}
                  </p>`}
          `
        : html`<p>${t('goalEntry')}</p>`}
      <div class="bottom">
        <span class="badge" title=${t('goalSimulationHint')}>${t('goalSimulation')}</span>
        <div class="actions">
          <button
            @click=${actions.edit}
            aria-haspopup="dialog"
            aria-label=${t(editable ? 'goalEdit' : 'goalNew')}
            title=${t(editable ? 'goalEdit' : 'goalNew')}
          >
            ${editable ? html`<ha-icon icon="mdi:pencil-outline"></ha-icon>` : t('goalNew')}
          </button>
          ${editable
            ? html`<button
                class="secondary"
                @click=${actions.cancel}
                aria-label=${t('goalCancel')}
                title=${t('goalCancel')}
              >
                <ha-icon icon="mdi:close"></ha-icon>
              </button>`
            : nothing}
        </div>
      </div>
    </section>
    <growatt-thor-goal-dialog
      .language=${language}
      .dark=${dark}
      .currency=${goal?.currency || 'EUR'}
    ></growatt-thor-goal-dialog>`;
}
