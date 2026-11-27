import { html, nothing } from 'lit';
import type { PvTranslator } from './locales';
import type { PvProfileFeedback } from './model';

export function renderPvProfileFeedback(feedback: PvProfileFeedback | null, t: PvTranslator) {
  if (!feedback) return nothing;
  const { key, busy, tone, done, total } = feedback;
  return html`<div class="notice pv-progress ${tone}" role="status">
    <ha-icon
      class=${busy ? 'spinner' : ''}
      .icon=${busy
        ? 'mdi:loading'
        : tone === 'success'
          ? 'mdi:check-circle'
          : 'mdi:information-outline'}
    ></ha-icon>
    <span>
      ${t(key)}
      ${done !== undefined && total !== undefined
        ? html`<small
            >${t('pvApplySteps')
              .replace('{done}', String(done))
              .replace('{total}', String(total))}</small
          >`
        : nothing}
    </span>
  </div>`;
}
