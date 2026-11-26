/** Start/Stop and the related action buttons. */
import { html, nothing } from 'lit';
import type { CardActions } from './card-actions';
import type { CardViewModel } from './card-view-model';

export function renderActions(
  { inactive, status, t, auth, caps, vehicle }: CardViewModel,
  actions: CardActions,
) {
  return html`
    <div class="actions">
      ${inactive
        ? html`<div class="activation">
            <ha-icon .icon=${status.icon}></ha-icon><span>${t(status.key)}</span>
          </div>`
        : auth === 'home_assistant_rfid' ||
            (auth === 'plug_and_charge' && vehicle === 'vehicleConnected')
          ? html`<button
              class="action start"
              ?disabled=${!caps.start}
              @click=${() => actions.command('start')}
            >
              <ha-icon icon="mdi:play"></ha-icon>${t('start')}
            </button>`
          : html`<div class="activation" title=${t(`${auth}Hint`)}>
              <ha-icon
                .icon=${auth === 'rfid_only'
                  ? 'mdi:contactless-payment-circle-outline'
                  : auth === 'plug_and_charge'
                    ? 'mdi:power-plug-outline'
                    : 'mdi:help-circle-outline'}
              ></ha-icon
              ><span
                >${t(
                  auth === 'rfid_only'
                    ? 'presentCard'
                    : auth === 'plug_and_charge'
                      ? 'automaticStart'
                      : 'authUnknown',
                )}</span
              >
            </div>`}<button
        class="action stop"
        ?disabled=${!caps.stop}
        @click=${() => actions.command('stop')}
      >
        <ha-icon icon="mdi:stop"></ha-icon>${t('stop')}
      </button>
    </div>
    ${!inactive && (auth === 'rfid_only' || auth === 'plug_and_charge')
      ? html`<p class="activation-hint">${t(`${auth}Hint`)}</p>`
      : nothing}
  `;
}
