/** Command feedback, goal entry, footer links and the retained past fault. */
import { html, nothing } from 'lit';
import type { CardActions, CardFeedback } from './card-actions';
import type { CardViewModel } from './card-view-model';

export function renderCommandFeedback({ info, t }: CardViewModel, feedback: CardFeedback) {
  // HA also rejects the service promise for a local policy denial. Keep the
  // specific explanation instead of masking it with the generic call error.
  const localDenial = info.key === 'localStartDenied';
  const messageKey = localDenial
    ? info.key
    : feedback.error || (feedback.sending ? 'localPending' : info.key);
  return html`
    ${feedback.error || feedback.sending || info.key
      ? html`<div
          class="notice ${feedback.error || localDenial || info.key === 'commandRejected'
            ? 'error'
            : 'warning'}"
          role="status"
        >
          <ha-icon
            class=${info.pending || feedback.sending ? 'spinner' : ''}
            icon="mdi:information-outline"
          ></ha-icon
          >${t(messageKey)}
        </div>`
      : nothing}
  `;
}

export function renderFooter(
  { t, caps, data, format, currentLimit, entity, fault, status }: CardViewModel,
  actions: CardActions,
) {
  return html`
    <slot name="goal-preview"
      ><button class="goal-entry" aria-haspopup="dialog" @click=${() => actions.openGoalPreview()}>
        <ha-icon icon="mdi:target"></ha-icon
        ><span><strong>${t('goalTitle')}</strong><small>${t('goalEntry')}</small></span
        ><span class="preview-badge"
          >${t(data.charging_target_pilot ? 'goalLivePilot' : 'goalPreview')}</span
        ><ha-icon icon="mdi:chevron-right"></ha-icon></button
    ></slot>
    <footer>
      <button
        class="text-button"
        ?disabled=${!caps.limit}
        title=${t('settingHint')}
        @click=${() => actions.moreInfo(data.entities.max_current)}
      >
        ${t('limit')} <strong>${format(currentLimit, 0)} A</strong
        ><ha-icon icon="mdi:chevron-right"></ha-icon></button
      ><button class="text-button" @click=${() => actions.moreInfo(entity.entity_id)}>
        ${t('details')}<ha-icon icon="mdi:arrow-top-right"></ha-icon>
      </button>
    </footer>
    ${fault && !['unknown', 'unavailable'].includes(fault.state) && status.key !== 'faulted'
      ? html`<details>
          <summary>${t('pastFault')}</summary>
          <p>${fault.attributes.message || fault.state}</p>
          <button class="text-button" @click=${() => actions.moreInfo(fault.entity_id)}>
            ${t('viewEntity')}
          </button>
        </details>`
      : nothing}
  `;
}
