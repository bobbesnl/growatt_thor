import { html, nothing } from 'lit';
import type { ThorPvLinkageDialog } from './dialog';
import { meterLabel } from './model';
import type { PvTranslator } from './locales';

const steps = ['pvStepPrerequisites', 'pvStepBehavior', 'pvStepReview'];
const option = (active: boolean, icon: string, title: string, hint: string, click: () => void) =>
  html`<button class="choice ${active ? 'selected' : ''}" aria-pressed=${active} @click=${click}>
    <ha-icon .icon=${icon}></ha-icon><span><strong>${title}</strong><small>${hint}</small></span
    ><ha-icon class="check" .icon=${active ? 'mdi:check-circle' : 'mdi:circle-outline'}></ha-icon>
  </button>`;

function prerequisites(dialog: ThorPvLinkageDialog, t: PvTranslator) {
  const data = dialog.cardData;
  const pv = dialog.pvData;
  const meterOk = data?.external_meter_health === 'healthy';
  const chargerOk = !pv?.blocked_reason || pv.blocked_reason === 'external_meter_not_ready';
  return html`<section>
    <h3>${t('pvPrerequisites')}</h3>
    <p class="lead">${t('pvPrerequisitesHint')}</p>
    <div class="checks">
      <div class=${meterOk ? 'ok' : 'blocked'}>
        <ha-icon .icon=${meterOk ? 'mdi:check-circle' : 'mdi:alert-circle'}></ha-icon
        ><span
          ><small>${t('pvMeter')}</small
          ><strong>${t(meterLabel(data?.external_meter_health || 'not_reported'))}</strong></span
        >
      </div>
      <div class=${chargerOk ? 'ok' : 'blocked'}>
        <ha-icon .icon=${chargerOk ? 'mdi:check-circle' : 'mdi:alert-circle'}></ha-icon
        ><span
          ><small>${t('pvCharger')}</small
          ><strong
            >${t(pv?.blocked_reason ? `pvBlocked_${pv.blocked_reason}` : 'pvChargerReady')}</strong
          ></span
        >
      </div>
    </div>
  </section>`;
}

function behavior(dialog: ThorPvLinkageDialog, t: PvTranslator) {
  const d = dialog.draft;
  return html`<section>
    <h3>${t('pvModeTitle')}</h3>
    <div class="choice-grid">
      ${option(
        d.workingMode === 'pv_linkage_plus',
        'mdi:white-balance-sunny',
        t('pvModePlus'),
        t('pvModePlusHint'),
        () => dialog.setMode('pv_linkage_plus'),
      )}
      ${option(
        d.workingMode === 'pv_linkage',
        'mdi:transmission-tower',
        t('pvModeRegular'),
        t('pvModeRegularHint'),
        () => dialog.setMode('pv_linkage'),
      )}
    </div>
    ${d.workingMode === 'pv_linkage'
      ? html`<label class="field"
          ><span>${t('pvGridLimit')}</span><small>${t('pvGridLimitHint')}</small>
          <div>
            <input
              type="number"
              min="0"
              max="22"
              step="0.1"
              .value=${d.gridImportLimitKw}
              @input=${(e: Event) =>
                dialog.setField('gridImportLimitKw', (e.target as HTMLInputElement).value)}
            /><b>kW</b>
          </div></label
        >`
      : nothing}
    <h3>${t('pvBoostTitle')}</h3>
    <div class="segments">
      ${(['disabled', 'manual', 'smart'] as const).map(
        (mode) =>
          html`<button
            class=${d.boostMode === mode ? 'selected' : ''}
            aria-pressed=${d.boostMode === mode}
            @click=${() => dialog.setBoost(mode)}
          >
            ${t(`pvBoost_${mode}`)}
          </button>`,
      )}
    </div>
    ${d.boostMode === 'manual'
      ? html`<div class="fields">
          <label
            ><span>${t('pvManualStart')}</span
            ><input
              type="time"
              .value=${d.manualStart}
              @input=${(e: Event) =>
                dialog.setField('manualStart', (e.target as HTMLInputElement).value)} /></label
          ><label
            ><span>${t('pvManualEnd')}</span
            ><input
              type="time"
              .value=${d.manualEnd}
              @input=${(e: Event) =>
                dialog.setField('manualEnd', (e.target as HTMLInputElement).value)}
          /></label>
        </div>`
      : nothing}
    ${d.boostMode === 'smart'
      ? html`<div class="fields">
            <label
              ><span>${t('pvSmartFinish')}</span
              ><input
                type="time"
                .value=${d.smartFinish}
                @input=${(e: Event) =>
                  dialog.setField('smartFinish', (e.target as HTMLInputElement).value)} /></label
            ><label
              ><span>${t('pvSmartEnergy')}</span>
              <div>
                <input
                  type="number"
                  min="0.1"
                  max="200"
                  step="0.1"
                  .value=${d.smartTargetEnergyKwh}
                  @input=${(e: Event) =>
                    dialog.setField('smartTargetEnergyKwh', (e.target as HTMLInputElement).value)}
                /><b>kWh</b>
              </div></label
            >
          </div>
          <aside class="smart-help">
            <ha-icon icon="mdi:clock-check-outline"></ha-icon>
            <span><strong>${t('pvSmartHelpTitle')}</strong><small>${t('pvSmartHelp')}</small></span>
          </aside>`
      : nothing}
    ${d.boostMode !== 'disabled'
      ? html`<p class="warning">
          <ha-icon icon="mdi:transmission-tower-import"></ha-icon>${t('pvBoostWarning')}
        </p>`
      : nothing}
    ${dialog.errors.map((error) => html`<p class="error" role="alert">${t(error)}</p>`)}
  </section>`;
}

function review(dialog: ThorPvLinkageDialog, t: PvTranslator) {
  const d = dialog.draft;
  const boostDetail =
    d.boostMode === 'manual'
      ? `${d.manualStart}–${d.manualEnd}`
      : d.boostMode === 'smart'
        ? `${d.smartTargetEnergyKwh} kWh · ${d.smartFinish}`
        : '';
  return html`<section>
    <h3>${t('pvReviewTitle')}</h3>
    <dl>
      <div>
        <dt>${t('pvReviewMode')}</dt>
        <dd>${t(d.workingMode === 'pv_linkage_plus' ? 'pvModePlus' : 'pvModeRegular')}</dd>
      </div>
      <div>
        <dt>${t('pvGridLimit')}</dt>
        <dd>
          ${d.workingMode === 'pv_linkage' ? `${d.gridImportLimitKw} kW` : t('pvReviewNoGrid')}
        </dd>
      </div>
      <div>
        <dt>${t('pvReviewBoost')}</dt>
        <dd>${t(`pvBoost_${d.boostMode}`)}${boostDetail ? ` · ${boostDetail}` : ''}</dd>
      </div>
    </dl>
    <p class="warning"><ha-icon icon="mdi:shield-check-outline"></ha-icon>${t('pvApplyWarning')}</p>
  </section>`;
}

export const renderPvLinkageDialog = (dialog: ThorPvLinkageDialog, t: PvTranslator) =>
  html`<dialog
    aria-labelledby="pv-title"
    @cancel=${(e: Event) => {
      if (dialog.busy) e.preventDefault();
    }}
  >
    <div class="heading">
      <div>
        <span>GROWATT · THOR</span>
        <h2 id="pv-title">${t('pvTitle')}</h2>
      </div>
      <button
        class="icon"
        aria-label=${t('pvCancel')}
        ?disabled=${dialog.busy}
        @click=${() => dialog.close()}
      >
        <ha-icon icon="mdi:close"></ha-icon>
      </button>
    </div>
    <nav aria-label="Progress">
      ${steps.map(
        (label, index) =>
          html`<div class=${index === dialog.step ? 'active' : index < dialog.step ? 'done' : ''}>
            <i>${index < dialog.step ? '✓' : index + 1}</i><span>${t(label)}</span>
          </div>`,
      )}
    </nav>
    ${dialog.step === 0
      ? prerequisites(dialog, t)
      : dialog.step === 1
        ? behavior(dialog, t)
        : review(dialog, t)}
    ${dialog.error ? html`<p class="error" role="alert">${t(dialog.error)}</p>` : nothing}
    <footer>
      <button
        ?disabled=${dialog.busy}
        @click=${() => (dialog.step ? dialog.back() : dialog.close())}
      >
        ${dialog.step ? t('pvBack') : t('pvCancel')}</button
      >${dialog.step < 2
        ? html`<button
            class="primary"
            ?disabled=${dialog.busy ||
            (dialog.step === 0 ? !!dialog.blockedReason : !!dialog.errors.length)}
            @click=${() => dialog.next()}
          >
            ${t('pvNext')}
          </button>`
        : html`<button
            class="primary"
            ?disabled=${dialog.busy || !!dialog.blockedReason || !!dialog.errors.length}
            @click=${() => dialog.apply()}
          >
            ${dialog.busy ? t('pvApplying') : t('pvApply')}
          </button>`}
    </footer>
  </dialog>`;
