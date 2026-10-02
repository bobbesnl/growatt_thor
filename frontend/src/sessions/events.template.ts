import { html, nothing } from 'lit';
import { translate } from '../shared/strings';
import type { SessionEvent, SessionEventType } from '../shared/types';
import { sessionTranslate, type SessionKey } from './locales';
import { sessionEventMarkers, sessionEventTone, type SessionEventTone } from './model';

const EVENT_LABELS: Record<SessionEventType, SessionKey> = {
  plugged_in: 'eventPluggedIn',
  transaction_started: 'eventTransactionStarted',
  energy_flow_started: 'eventEnergyFlowStarted',
  charging_paused: 'eventChargingPaused',
  energy_flow_stopped: 'eventEnergyFlowStopped',
  stop_requested: 'eventStopRequested',
  transaction_stopped: 'eventTransactionStopped',
  unplugged: 'eventUnplugged',
};

export function sessionEventLabel(
  types: SessionEventType[],
  provisional: boolean,
  language: string,
): string {
  const t = sessionTranslate(language);
  const label = types.map((type) => t(EVENT_LABELS[type])).join(' · ');
  return provisional ? `${label} (${t('eventProvisional')})` : label;
}

/** Status reasons share the charger's translated vocabulary. Other OCPP reasons stay intact. */
export function sessionEventReason(
  reason: string | undefined,
  language: string,
): string | undefined {
  return reason && ['suspended_ev', 'suspended_evse'].includes(reason)
    ? translate(language)(reason)
    : reason;
}

/** One palette for chart markers and the compact event list, in both themes. */
export function sessionEventColors(dark: boolean): Record<SessionEventTone, string> {
  return {
    lime: '#8bc53f',
    blue: dark ? '#79c7f2' : '#2f7fb8',
    amber: dark ? '#efbe6b' : '#b36f14',
    coral: dark ? '#f1966f' : '#db7447',
    neutral: dark ? '#a4b3a6' : '#6c7b72',
  };
}

/** Keep exact event times even when the wide chart groups nearby markers. */
export function renderSessionEvents(
  events: SessionEvent[] | undefined,
  language: string,
  dark: boolean,
) {
  const markers = sessionEventMarkers(events);
  if (!markers.length) return nothing;
  const t = sessionTranslate(language);
  const colors = sessionEventColors(dark);
  const date = new Intl.DateTimeFormat(language, { month: 'short', day: 'numeric' });
  const time = new Intl.DateTimeFormat(language, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
  let previousDay: string | undefined;
  return html`<section class="chart-events" aria-label=${t('seriesEvents')}>
    <div class="curve-title">${t('seriesEvents')}</div>
    <ol tabindex="0" aria-label=${t('seriesEvents')}>
      ${markers.flatMap((marker) =>
        marker.events.map((event) => {
          const at = new Date(event.at);
          const day = at.toDateString();
          const newDay = day !== previousDay;
          previousDay = day;
          const fullTime = at.toLocaleString(language);
          return html`<li style=${`--event-color: ${colors[sessionEventTone([event])]}`}>
            ${newDay ? html`<span class="chart-event-day">${date.format(at)}</span>` : nothing}
            <div class="chart-event-entry">
              <time datetime=${event.at} aria-label=${fullTime} title=${fullTime}
                >${time.format(at)}</time
              >
              <span class="chart-event-track" aria-hidden="true"></span>
              <span class="chart-event-text">
                <strong
                  class="chart-event-title ${event.certainty === 'provisional'
                    ? 'provisional'
                    : ''}"
                >
                  ${sessionEventLabel([event.type], event.certainty === 'provisional', language)}
                </strong>
                ${event.reason
                  ? html`<span>${sessionEventReason(event.reason, language)}</span>`
                  : nothing}
              </span>
            </div>
          </li>`;
        }),
      )}
    </ol>
  </section>`;
}
