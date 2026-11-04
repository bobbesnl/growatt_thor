import { html } from 'lit';
import { renderEnergyStop } from '../shared/energy-stop';
import {
  liveGoalAvailable,
  liveTargetStatus,
  oneTimeGoalAvailable,
  scheduledGoalAvailable,
} from '../targets/live';
import type { CardActions, CardFeedback } from './card-actions';
import type { CardViewModel } from './card-view-model';
import { renderHeader, renderStatus } from './header.template';
import { renderHero } from './hero.template';
import { renderSession, renderTargetNotice, renderWarnings } from './session.template';
import { renderActions } from './actions.template';
import { renderCommandFeedback, renderFooter } from './footer.template';

export type { CardActions } from './card-actions';

export function renderCard(view: CardViewModel, actions: CardActions, feedback: CardFeedback) {
  const { inactive, status, vehicle, currency, t, dark, hass } = view;
  return html` <ha-card
      class="card ${inactive ? 'is-inactive' : ''} ${dark ? 'dark' : ''}"
      data-tone=${status.tone}
    >
      ${renderHeader(view, actions)} ${renderStatus(view)} ${renderHero(view)}
      <div class="vehicle">
        <ha-icon
          .icon=${vehicle === 'vehicleConnected'
            ? 'mdi:ev-plug-type2'
            : vehicle === 'vehicleDisconnected'
              ? 'mdi:power-plug-off-outline'
              : 'mdi:help-circle-outline'}
        ></ha-icon
        >${t(vehicle)}
      </div>
      <p class="hint">${t(status.hint)}</p>
      ${renderEnergyStop(view.data.energy_stop, hass.language || hass.locale?.language || 'en')}
      ${renderWarnings(view)} ${renderSession(view)} ${renderActions(view, actions)}
      ${renderTargetNotice(view)} ${renderCommandFeedback(view, feedback)}
      ${renderFooter(view, actions)} </ha-card
    ><growatt-thor-goal-dialog
      .live=${view.data.charging_target_pilot
        ? {
            available: liveGoalAvailable(hass, view.entity, view.data),
            scheduleOnceAvailable: oneTimeGoalAvailable(hass, view.entity, view.data),
            scheduleDailyAvailable: scheduledGoalAvailable(hass, view.entity, view.data),
            request: view.data.charging_target,
            status: liveTargetStatus(view.data),
            save: actions.setGoal,
            cancel: actions.cancelGoal,
          }
        : undefined}
      .timeZone=${hass.config?.time_zone || 'UTC'}
      .language=${hass.language || hass.locale?.language || 'en'}
      .dark=${dark}
      .currency=${currency}
    ></growatt-thor-goal-dialog
    ><growatt-thor-auth-dialog .hass=${hass} .dark=${dark}></growatt-thor-auth-dialog
    ><growatt-thor-pv-linkage-dialog .hass=${hass} .dark=${dark}></growatt-thor-pv-linkage-dialog>`;
}
