import { html, nothing } from 'lit';
import { ref, type Ref } from 'lit/directives/ref.js';
import type { SessionItem, SessionHistoryData } from '../shared/types';
import { formatSessionDate, formatSessionNumber, sessionPage, type SessionSort } from './model';
import { sessionTranslate } from './locales';
import type { SessionDetailStore } from './detail-store';
import { sessionMetricViews, sessionGreenTotalView } from './metrics.template';
import { renderSessionAccounting } from './accounting.template';
import { renderSessionEvents } from './events.template';
import { renderSessionIdentifier } from './identifier.template';
import { renderSessionList } from './list.template';

interface SessionCardView {
  name: string;
  dark: boolean;
  language: string;
  timeZone: string;
  currency: string;
  data: SessionHistoryData;
  page: ReturnType<typeof sessionPage<SessionItem>>;
  selected?: SessionItem;
  query: string;
  sort: SessionSort;
  ascending: boolean;
  showCurve: boolean;
  showIdentifier: boolean;
  curveStatus: ReturnType<SessionDetailStore['status']>;
  chartRef: Ref<HTMLDivElement>;
  tableRef: Ref<HTMLDivElement>;
}
interface SessionCardActions {
  search(event: InputEvent): void;
  sort(key: SessionSort): void;
  selectSession(id: string | null): void;
  goToPage(index: number, scrollToList?: boolean): void;
}

export function renderSessionCard(view: SessionCardView, actions: SessionCardActions) {
  const { dark, name, selected, language, currency } = view;
  return html`<ha-card class="card ${dark ? 'dark' : ''}"
    ><header><h2>${name}</h2></header>
    ${renderSessionKpis(view)} ${renderSessionToolbar(view, actions)} ${renderSessionCurve(view)}
    ${selected ? renderSessionAccounting(selected, language, currency) : nothing}
    ${renderSessionTable(view, actions)} ${renderSessionPagination(view, actions)}</ha-card
  >`;
}

function sessionFormatting(view: SessionCardView) {
  const t = sessionTranslate(view.language);
  const fmt = (value: number | null) => formatSessionNumber(value, view.language);
  const fmtDate = (value: string | null | undefined) =>
    formatSessionDate(value, view.language, view.timeZone);
  return { t, fmt, fmtDate };
}

function renderSessionKpis(view: SessionCardView) {
  const { data, language, currency } = view;
  const { t, fmt } = sessionFormatting(view);
  const greenTotal = sessionGreenTotalView(data, language);
  return html`
    <section class="kpis">
      <div class="kpi">
        <span>${t('energy')}</span><strong>${fmt(data.total_energy_kwh)} kWh</strong>
      </div>
      <div class="kpi green">
        <span>${t('green')}</span><strong title=${greenTotal.title}>${greenTotal.text}</strong>
      </div>
      <div class="kpi">
        <span>${t('chargerCost')}</span><strong>${fmt(data.total_cost)} ${currency}</strong>
      </div>
      <div class="kpi"><span>${t('sessions')}</span><strong>${data.total_count}</strong></div>
    </section>
  `;
}

function renderSessionToolbar(view: SessionCardView, actions: SessionCardActions) {
  const t = sessionTranslate(view.language);
  return html`
    <div class="toolbar">
      <input
        class="search"
        type="search"
        .value=${view.query}
        aria-label=${t('search')}
        placeholder=${t('search')}
        @input=${actions.search}
      />
    </div>
  `;
}

function renderSessionCurve(view: SessionCardView) {
  const { selected, language, dark, timeZone } = view;
  const { t, fmtDate } = sessionFormatting(view);
  return !view.showCurve
    ? nothing
    : html`<section class="curve">
        <div class="curve-title">
          ${t('chart')} · ${fmtDate(selected?.start_time)}
          ${selected?.active ? ` · ${t('active')}` : ''}
        </div>
        <div class="chart-area">
          <div class="chart" role="img" aria-label=${t('chart')} ${ref(view.chartRef)}></div>
          ${selected?.power_curve?.length
            ? nothing
            : html`<div class="no-curve">
                ${view.curveStatus === 'loading'
                  ? t('loadingCurve')
                  : view.curveStatus === 'error'
                    ? t('curveLoadError')
                    : selected?.active
                      ? t('waitingCurve')
                      : t('noCurve')}
              </div>`}
        </div>
        ${renderSessionEvents(selected?.events, language, dark, timeZone)}
      </section>`;
}

function renderSessionTable(view: SessionCardView, actions: SessionCardActions) {
  const { page, selected, language, timeZone, currency } = view;
  const rows = page.items;
  const t = sessionTranslate(language);
  const head = (key: SessionSort, label: string, cls = '') =>
    html`<th class=${cls}>
      <button @click=${() => actions.sort(key)}>
        ${label}${view.sort === key ? (view.ascending ? ' ↑' : ' ↓') : ''}
      </button>
    </th>`;
  return html`
    <div class="table-wrap" ${ref(view.tableRef)}>
      <table class="session-table">
        <thead>
          <tr>
            ${head('start', t('start'))}${head('end', t('end'), 'optional')}${head(
              'energy',
              t('energy'),
              'num',
            )}${head('green', t('green'), 'num optional')}${head(
              'cost',
              t('cost'),
              'num',
            )}${!view.showIdentifier ? nothing : head('identifier', t('identifier'))}
          </tr>
        </thead>
        <tbody>
          ${rows.length
            ? rows.map((row) => renderSessionRow(row, view, actions))
            : html`<tr>
                <td class="empty" colspan="6">${t('noData')}</td>
              </tr>`}
        </tbody>
      </table>
      ${renderSessionList({
        rows,
        selectedId: selected?.session_id,
        language,
        timeZone,
        currency,
        showIdentifier: view.showIdentifier,
        sort: view.sort,
        ascending: view.ascending,
        onSort: (key) => actions.sort(key),
        onSelect: (id) => actions.selectSession(id),
      })}
    </div>
  `;
}

function renderSessionRow(row: SessionItem, view: SessionCardView, actions: SessionCardActions) {
  const { selected, language, currency } = view;
  const { t, fmt, fmtDate } = sessionFormatting(view);
  const metrics = sessionMetricViews(row, language, currency);
  return html`<tr
    class=${[
      row.session_id === selected?.session_id ? 'selected' : '',
      row.active ? 'active-session' : '',
    ]
      .filter(Boolean)
      .join(' ')}
    tabindex="0"
    aria-selected=${row.session_id === selected?.session_id}
    @click=${() => actions.selectSession(row.session_id)}
    @keydown=${(event: KeyboardEvent) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        actions.selectSession(row.session_id);
      }
    }}
  >
    <td>
      ${fmtDate(row.start_time)}
      ${row.session_id ? html`<small class="session-id">ID: ${row.session_id}</small>` : nothing}
      ${row.active ? html`<span class="active-badge">${t('active')}</span>` : nothing}
    </td>
    <td class="optional">${row.active ? t('active') : fmtDate(row.end_time)}</td>
    <td class="num">
      ${row.energy_source === 'power_fallback' ? '≈ ' : ''}${fmt(row.energy_kwh)} kWh
    </td>
    <td class="num optional">${metrics.green}</td>
    <td class="num">${metrics.cost}${metrics.costBasis}</td>
    ${!view.showIdentifier ? nothing : html`<td>${renderSessionIdentifier(row)}</td>`}
  </tr>`;
}

function renderSessionPagination(view: SessionCardView, actions: SessionCardActions) {
  const { page } = view;
  const t = sessionTranslate(view.language);
  return page.total
    ? html`<nav class="table-pagination" aria-label=${t('page')}>
        <span class="page-range">${page.from}–${page.to} / ${page.total}</span>
        <div class="page-controls">
          <button
            type="button"
            aria-label=${t('previousPage')}
            title=${t('previousPage')}
            ?disabled=${page.index === 0}
            @click=${() => actions.goToPage(page.index - 1, true)}
          >
            ‹
          </button>
          <span aria-live="polite">${t('page')} ${page.index + 1} / ${page.count}</span>
          <button
            type="button"
            aria-label=${t('nextPage')}
            title=${t('nextPage')}
            ?disabled=${page.index >= page.count - 1}
            @click=${() => actions.goToPage(page.index + 1, true)}
          >
            ›
          </button>
        </div>
      </nav>`
    : nothing;
}
