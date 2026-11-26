import { sessionEventLabel, sessionEventReason, sessionEventColors } from './event-model';
import { calendarDay } from '../shared/time';
import { html, nothing } from 'lit';
import type { SessionEvent } from '../shared/types';
import { sessionTranslate } from './locales';
import { sessionEventMarkers, sessionEventTone } from './model';

/** Keep exact event times even when the wide chart groups nearby markers. */
export function renderSessionEvents(
  events: SessionEvent[] | undefined,
  language: string,
  dark: boolean,
  timeZone = 'UTC',
) {
  const markers = sessionEventMarkers(events);
  if (!markers.length) return nothing;
  const t = sessionTranslate(language);
  const colors = sessionEventColors(dark);
  const date = new Intl.DateTimeFormat(language, { timeZone, month: 'short', day: 'numeric' });
  const time = new Intl.DateTimeFormat(language, {
    timeZone,
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
          const day = calendarDay(at.getTime(), timeZone);
          const newDay = day !== previousDay;
          previousDay = day;
          const fullTime = at.toLocaleString(language, { timeZone });
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
