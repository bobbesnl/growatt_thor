/** Card header: name, mode and authorization pills, and the status strip. */
import { html, nothing } from 'lit';
import type { CardActions } from './card-actions';
import type { CardViewModel } from './card-view-model';

export function renderHeader(
  { config, t, data, auth, entity, rebooting }: CardViewModel,
  actions: CardActions,
) {
  return html`
    <header>
      <div class="eyebrow">GROWATT · THOR</div>
      <h2 title=${config.name || t('statusEntity')}>${config.name || t('statusEntity')}</h2>
      <div class="pills">
        ${data.pv_linkage
          ? html`<button
              class="mode strategy"
              title=${t('chargeMode')}
              aria-haspopup="dialog"
              ?disabled=${rebooting}
              @click=${() => actions.openPv(entity.entity_id, data.pv_linkage)}
            >
              <ha-icon
                .icon=${data.working_mode?.startsWith('pv_')
                  ? 'mdi:white-balance-sunny'
                  : data.working_mode === 'off_peak'
                    ? 'mdi:clock-outline'
                    : 'mdi:lightning-bolt'}
              ></ha-icon
              >${t(data.working_mode || 'modeUnknown')}
            </button>`
          : html`<div class="mode" title=${t('chargeMode')}>
              <ha-icon
                .icon=${data.working_mode?.startsWith('pv_')
                  ? 'mdi:white-balance-sunny'
                  : data.working_mode === 'off_peak'
                    ? 'mdi:clock-outline'
                    : 'mdi:lightning-bolt'}
              ></ha-icon
              >${t(data.working_mode || 'modeUnknown')}
            </div>`}
        <button
          class="mode auth"
          title=${t(`${auth}Hint`)}
          aria-label=${t('authorization')}
          ?disabled=${!data.entities.authorization_mode_control || rebooting}
          @click=${() => actions.openAuth(data.entities.authorization_mode_control)}
        >
          <ha-icon
            .icon=${auth === 'plug_and_charge'
              ? 'mdi:power-plug-outline'
              : 'mdi:card-account-details-outline'}
          ></ha-icon
          >${t(auth)}
        </button>
      </div>
    </header>
  `;
}

export function renderStatus({ status, t, powerFlow, format }: CardViewModel) {
  return html`<div class="status-strip">
    <div class="status" role="status">
      <span class="dot"></span><ha-icon .icon=${status.icon}></ha-icon>${t(status.key)}
    </div>
    ${powerFlow.visible
      ? html`<div
          class="grid-balance"
          data-flow=${powerFlow.tone}
          title=${t('gridPower')}
          aria-label=${`${t(powerFlow.label)}: ${
            powerFlow.valueKw === null ? t('missing') : `${format(powerFlow.valueKw)} kW`
          }`}
        >
          <ha-icon .icon=${powerFlow.icon}></ha-icon><span>${t(powerFlow.label)}</span
          ><strong>${powerFlow.valueKw === null ? '—' : `${format(powerFlow.valueKw)} kW`}</strong>
        </div>`
      : nothing}
  </div>`;
}
