import { html, nothing } from 'lit';
import type { SessionItem } from '../shared/types';
import { formatSessionPeriod, formatSessionNumber, type SessionSort } from './model';
import { sessionTranslate } from './locales';
import { sessionMetricViews } from './metrics.template';

interface SessionListView {
  rows: SessionItem[];
  selectedId: string | null | undefined;
  language: string;
  currency: string;
  showIdentifier: boolean;
  sort: SessionSort;
  ascending: boolean;
  onSort: (key: SessionSort) => void;
  onSelect: (id: string | null) => void;
}

/** Both layouts share the same paged rows and selection; resizing never resets them. */
export function renderSessionList(view: SessionListView) {
  const t = sessionTranslate(view.language);
  const fmt = (value: number | null) => formatSessionNumber(value, view.language);
  const sorts: SessionSort[] = ['start', 'end', 'energy', 'green', 'cost'];
  if (view.showIdentifier) sorts.push('identifier');
  const metric = (label: string, value: unknown, cls = '') => html`
    <span class="session-metric ${cls}"><span>${label}</span><strong>${value}</strong></span>
  `;
  return html`<div class="session-list-view">
    <div class="list-sort">
      <label>
        <span>${t('sortBy')}</span>
        <select
          @change=${(event: Event) =>
            view.onSort((event.target as HTMLSelectElement).value as SessionSort)}
        >
          ${sorts.map(
            (key) => html`<option value=${key} ?selected=${view.sort === key}>${t(key)}</option>`,
          )}
        </select>
      </label>
      <button
        type="button"
        @click=${() => view.onSort(view.sort)}
        aria-label=${view.ascending ? t('descending') : t('ascending')}
        title=${view.ascending ? t('descending') : t('ascending')}
      >
        ${view.ascending ? '↑' : '↓'}
      </button>
    </div>
    ${view.rows.length
      ? html`<ul class="session-list" aria-label=${t('sessions')}>
          ${view.rows.map((row) => {
            const period = formatSessionPeriod(row.start_time, row.end_time, view.language);
            const metrics = sessionMetricViews(row, view.language, view.currency);
            return html`<li>
              <button
                type="button"
                class="session-tile ${row.active ? 'active-session' : ''}"
                aria-pressed=${row.session_id === view.selectedId}
                @click=${() => view.onSelect(row.session_id)}
              >
                <span class="session-tile-heading">
                  ${period.day ? html`<strong class="session-day">${period.day}</strong>` : nothing}
                  ${row.session_id
                    ? html`<small class="session-id">ID: ${row.session_id}</small>`
                    : nothing}
                  ${row.active ? html`<span class="active-badge">${t('active')}</span>` : nothing}
                </span>
                <span class="session-times">
                  ${metric(t('start'), period.start)}
                  ${metric(t('end'), row.active ? t('active') : period.end)}
                </span>
                <span class="session-metrics">
                  ${metric(metrics.costLabel ?? t('cost'), metrics.cost)}
                  <span class="session-energy-metrics">
                    ${metric(
                      t('energy'),
                      html`${row.energy_source === 'power_fallback' ? '≈ ' : ''}${fmt(
                        row.energy_kwh,
                      )}
                      kWh`,
                    )}
                    ${metric(t('green'), metrics.green)}
                  </span>
                  ${view.showIdentifier
                    ? metric(
                        t('identifier'),
                        row.authorized_identifier || '—',
                        'session-identifier',
                      )
                    : nothing}
                </span>
              </button>
            </li>`;
          })}
        </ul>`
      : html`<div class="empty">${t('noData')}</div>`}
  </div>`;
}
