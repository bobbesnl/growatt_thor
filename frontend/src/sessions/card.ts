import { tokenStyles } from '../shared/styles';
import { renderSessionAccounting } from './accounting.template';
import { cardInitialization } from '../shared/card-initialization';
import { cardNoticeStyles, renderCardNotice } from '../shared/card-notice';
import { sessionMetricViews, sessionGreenTotalView } from './metrics.template';
import { LitElement, html, nothing, unsafeCSS } from 'lit';
import { createRef, ref, type Ref } from 'lit/directives/ref.js';
import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import {
  DataZoomInsideComponent,
  DataZoomSliderComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
} from 'echarts/components';
import { AxisBreak } from 'echarts/features';
import { CanvasRenderer } from 'echarts/renderers';
import cssText from './card.css';
import { resolveEntity, statusEntities } from '../shared/model';
import {
  formatSessionDate,
  formatSessionNumber,
  sessionChartBreaks,
  sessionChartExtent,
  sessionChartPoints,
  sessionChartSpansDaysInZone,
  sessionEventMarkers,
  sessionContextPoints,
  selectedSession,
  sessionRows,
  sessionPage,
  type SessionSort,
} from './model';
import { sessionTranslate } from './locales';
import { renderSessionList } from './list.template';
import { renderSessionIdentifier } from './identifier.template';
import { renderSessionEvents } from './events.template';
import { SessionDetailStore } from './detail-store';
import { SessionChartHost, bindSessionChartEvents } from './chart-host';
import { chartPalette } from '../shared/palette';
import {
  buildSessionChartOption,
  buildSessionEventMarkLine,
  SESSION_COMPACT_WIDTH_PX,
  CHART_ANIMATION_MS,
  WATTS_PER_KILOWATT,
  type SessionChartModel,
} from './chart-options';
import type {
  Hass,
  SessionCardConfig,
  SessionDetailResponse,
  SessionHistoryData,
  SessionItem,
} from '../shared/types';
import './editor';
echarts.use([
  LineChart,
  AxisBreak,
  DataZoomInsideComponent,
  DataZoomSliderComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
  CanvasRenderer,
]);

export class ThorSessionCard extends LitElement {
  static styles = [tokenStyles, unsafeCSS(cssText), cardNoticeStyles];
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
    _query: { state: true },
    _sort: { state: true },
    _ascending: { state: true },
    _selectedSessionId: { state: true },
  };
  hass?: Hass;
  private _config: SessionCardConfig = { type: 'custom:growatt-thor-session-card' };
  private _query = '';
  private _sort: SessionSort = 'start';
  private _ascending = false;
  private _page = 0;
  private _selectedSessionId?: string;
  private readonly _details = new SessionDetailStore(() => {
    this._chartSessionKey = undefined;
    this.requestUpdate();
  });
  private readonly _chartHost = new SessionChartHost<echarts.ECharts>(
    (element) => echarts.init(element),
    () => this.drawChart(),
  );
  private get _chart() {
    return this._chartHost.chart;
  }
  private _legendSelected: Record<string, boolean> = {};
  private _dataZoomRange = { start: 0, end: 100 };
  private _expandedBreaks = new Set<string>();
  private _chartSessionKey?: string;
  private _eventLabelFadeKey?: string;
  private _labelFadeFrame?: number;
  private _chartRef: Ref<HTMLDivElement> = createRef();
  private _tableRef: Ref<HTMLDivElement> = createRef();
  setConfig(config: SessionCardConfig) {
    if (!config) throw new Error('Invalid configuration');
    if (
      config.rows !== undefined &&
      (!Number.isInteger(config.rows) || config.rows < 1 || config.rows > 20)
    )
      throw new Error('rows must be between 1 and 20');
    this._config = { ...config };
    this._page = 0;
  }
  static getConfigElement() {
    return document.createElement('growatt-thor-session-card-editor');
  }
  static getStubConfig(hass?: Hass) {
    const entity = hass && statusEntities(hass)[0];
    return { entity: entity?.entity_id, entry_id: entity?.attributes.thor_card.entry_id };
  }
  getCardSize() {
    return 6;
  }
  getGridOptions() {
    return { columns: 12, min_columns: 6, min_rows: 4 };
  }
  disconnectedCallback() {
    super.disconnectedCallback();
    this._details.clear();
    if (this._labelFadeFrame !== undefined) cancelAnimationFrame(this._labelFadeFrame);
    this._chartHost.disconnect();
  }
  willUpdate() {
    // Scope the cache before render() can merge details into the new entry's rows.
    // Doing this in updated() would allow one frame with the previous entry's data.
    const entity = this.hass && resolveEntity(this.hass, this._config);
    if (this._details.setEntry(entity?.attributes.thor_card?.entry_id || this._config.entry_id))
      this._chartSessionKey = undefined;
  }
  updated() {
    this.drawChart();
    void this.loadSelectedDetails();
  }
  private selectedSession(data: SessionHistoryData): SessionItem | undefined {
    return this._details.resolve(selectedSession(data.items, this._selectedSessionId));
  }
  private async loadSelectedDetails(): Promise<void> {
    const hass = this.hass;
    const entity = hass && resolveEntity(hass, this._config);
    const data = entity?.attributes.thor_card?.sessions;
    if (!hass || !data || this._config.show_curve === false) return;
    await this._details.load(
      selectedSession(data.items, this._selectedSessionId),
      hass.callWS
        ? (entryId, sessionId) =>
            hass.callWS!<SessionDetailResponse>({
              type: 'growatt_thor/session_detail',
              entry_id: entryId,
              session_id: sessionId,
            })
        : undefined,
    );
  }
  private drawChart() {
    const entity = this.hass && resolveEntity(this.hass, this._config);
    const data = entity?.attributes.thor_card?.sessions;
    const el = this._chartRef.value;
    if (!el || !data || this._config.show_curve === false) {
      this._chartHost.disconnect();
      return;
    }
    const attached = this._chartHost.attach(el);
    const chart = this._chartHost.chart;
    if (!chart) return;
    if (attached)
      bindSessionChartEvents(chart, {
        legend: (selected) => {
          this._legendSelected = selected;
          this.drawChart();
        },
        zoom: (range) => {
          this._dataZoomRange = range;
        },
        axisBreak: (key, expanded) => {
          if (expanded) this._expandedBreaks.add(key);
          else this._expandedBreaks.delete(key);
        },
      });
    const dark =
      this._config.theme === 'dark' ||
      (this._config.theme !== 'light' && !!this.hass?.themes?.darkMode);
    const compact = this.clientWidth <= SESSION_COMPACT_WIDTH_PX;
    const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const session = this.selectedSession(data);
    const sessionKey = session?.session_id || `${session?.start_time || 'unknown'}`;
    if (this._chartSessionKey !== sessionKey) {
      this._chartSessionKey = sessionKey;
      this._dataZoomRange = { start: 0, end: 100 };
      this._expandedBreaks.clear();
    }
    const points = sessionChartPoints(session?.power_curve || []);
    const measuredCurrents = sessionContextPoints(session?.measured_current_sum_curve_a);
    const configuredCurrents = sessionContextPoints(session?.configured_current_limit_curve_a);
    const pvSurplus = sessionContextPoints(session?.site_pv_surplus_curve_w, WATTS_PER_KILOWATT);
    const houseLoad = sessionContextPoints(session?.site_house_load_curve_w, WATTS_PER_KILOWATT);
    const batteryFlow = sessionContextPoints(
      session?.site_battery_curve_w,
      WATTS_PER_KILOWATT,
      true,
    );
    if (
      !points.length &&
      !measuredCurrents.length &&
      !configuredCurrents.length &&
      !pvSurplus.length &&
      !houseLoad.length &&
      !batteryFlow.length
    ) {
      this._chart?.clear();
      return;
    }
    const timeZone = this.hass?.config?.time_zone || 'UTC';
    const language = this.hass?.language || this.hass?.locale?.language || 'en';
    const t = sessionTranslate(language);
    const markers = sessionEventMarkers(session?.events);
    const chartSeries = [measuredCurrents, configuredCurrents, pvSurplus, houseLoad, batteryFlow];
    const chartBreaks = sessionChartBreaks(points, markers, ...chartSeries).map((axisBreak) => ({
      ...axisBreak,
      gap: '5%',
      isExpanded: this._expandedBreaks.has(`${axisBreak.start}:${axisBreak.end}`),
    }));
    const chartSpansDays = sessionChartSpansDaysInZone(timeZone, points, markers, ...chartSeries);
    const powerSeriesName = t('seriesPower');
    const measuredCurrentSeriesName = t('seriesMeasuredCurrentSum');
    const configuredCurrentSeriesName = t('seriesConfiguredCurrentLimit');
    const pvSurplusSeriesName = t('seriesPvSurplus');
    const houseLoadSeriesName = `${['site_balance', 'mixed'].includes(session?.site_house_load_source || '') ? '≈ ' : ''}${t('seriesHouseLoad')}`;
    const batteryFlowSeriesName = t('seriesBatteryFlow');
    const eventSeriesName = t('seriesEvents');
    const powerVisible = this._legendSelected[powerSeriesName] !== false;
    const pvSurplusVisible = this._legendSelected[pvSurplusSeriesName] !== false;
    const houseLoadVisible = this._legendSelected[houseLoadSeriesName] !== false;
    const batteryFlowVisible = this._legendSelected[batteryFlowSeriesName] !== false;
    const measuredCurrentVisible = this._legendSelected[measuredCurrentSeriesName] !== false;
    const configuredCurrentVisible = this._legendSelected[configuredCurrentSeriesName] !== false;
    const powerAxisVisible =
      (powerVisible && !!points.length) ||
      (pvSurplusVisible && !!pvSurplus.length) ||
      (houseLoadVisible && !!houseLoad.length) ||
      (batteryFlowVisible && !!batteryFlow.length);
    const currentAxisVisible =
      (measuredCurrentVisible && !!measuredCurrents.length) ||
      (configuredCurrentVisible && !!configuredCurrents.length);
    const eventLayerVisible = !compact && this._legendSelected[eventSeriesName] !== false;
    const extent = sessionChartExtent(
      points,
      markers,
      measuredCurrents,
      configuredCurrents,
      pvSurplus,
      houseLoad,
      batteryFlow,
    );
    const eventHost =
      powerVisible && points.length
        ? 'power'
        : pvSurplusVisible && pvSurplus.length
          ? 'pv'
          : houseLoadVisible && houseLoad.length
            ? 'house'
            : batteryFlowVisible && batteryFlow.length
              ? 'battery'
              : measuredCurrentVisible && measuredCurrents.length
                ? 'measured-current'
                : configuredCurrentVisible && configuredCurrents.length
                  ? 'configured-current'
                  : 'events';
    const fadeKey = `${session?.session_id || 'unknown'}:${eventHost}:${markers
      .map((marker) => `${marker.at}:${marker.events.map((event) => event.type).join(',')}`)
      .join('|')}`;
    const fadeEventLabels =
      eventLayerVisible &&
      !!markers.length &&
      !reducedMotion &&
      this._eventLabelFadeKey !== fadeKey;
    if (!eventLayerVisible) this._eventLabelFadeKey = undefined;
    else if (fadeEventLabels) this._eventLabelFadeKey = fadeKey;
    const chartModel: SessionChartModel = {
      points,
      measuredCurrents,
      configuredCurrents,
      pvSurplus,
      houseLoad,
      batteryFlow,
      markers,
      eventHost,
      eventLayerVisible,
      reducedMotion,
      fadeEventLabels,
      dark,
      compact,
      language,
      timeZone,
      chartSpansDays,
      powerAxisVisible,
      currentAxisVisible,
      extent,
      chartBreaks,
      legendSelected: this._legendSelected,
      zoomRange: this._dataZoomRange,
      powerSeriesName,
      pvSurplusSeriesName,
      houseLoadSeriesName,
      batteryFlowSeriesName,
      configuredCurrentSeriesName,
      measuredCurrentSeriesName,
      eventSeriesName,
    };
    chart.setOption(buildSessionChartOption(chartModel, chartPalette(dark), el.clientWidth), {
      notMerge: true,
    });
    if (this._labelFadeFrame !== undefined) cancelAnimationFrame(this._labelFadeFrame);
    if (fadeEventLabels) {
      this._labelFadeFrame = requestAnimationFrame(() => {
        this._labelFadeFrame = requestAnimationFrame(() => {
          if (this._eventLabelFadeKey !== fadeKey) return;
          this._chart?.setOption({
            animationDurationUpdate: CHART_ANIMATION_MS,
            animationEasingUpdate: 'cubicOut',
            series: [{ id: eventHost, markLine: buildSessionEventMarkLine(chartModel, 1) }],
          });
        });
      });
    }
  }
  private sort(key: SessionSort) {
    if (this._sort === key) this._ascending = !this._ascending;
    else {
      this._sort = key;
      this._ascending = key === 'identifier';
    }
    this.goToPage(0);
  }
  private async goToPage(index: number, scrollToList = false) {
    const changed = index !== this._page;
    this._page = index;
    if (this._tableRef.value) this._tableRef.value.scrollTop = 0;
    this.requestUpdate();
    if (!scrollToList || !changed) return;
    // Wait for the new page's height before scrolling the dashboard. Checking
    // the visible layout also handles narrow cards on otherwise wide screens.
    await this.updateComplete;
    const list = this.renderRoot.querySelector<HTMLElement>('.session-list-view');
    if (!this.isConnected || !list || getComputedStyle(list).display === 'none') return;
    list.scrollIntoView({
      block: 'start',
      behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
    });
  }
  private selectSession(sessionId: string | null) {
    this._selectedSessionId = sessionId || undefined;
    this._details.retry(sessionId);
    this._chartSessionKey = undefined;
  }
  render() {
    const timeZone = this.hass?.config?.time_zone || 'UTC';
    const language = this.hass?.language || this.hass?.locale?.language || 'en';
    const t = sessionTranslate(language);
    const entity = this.hass && resolveEntity(this.hass, this._config);
    const data = entity?.attributes.thor_card?.sessions;
    const dark =
      this._config.theme === 'dark' ||
      (this._config.theme !== 'light' && !!this.hass?.themes?.darkMode);
    const initialization = cardInitialization(this.hass, this._config, true);
    if (initialization !== 'ready' || !data)
      return renderCardNotice(
        initialization,
        language,
        dark,
        this._config.name || t('title'),
        true,
      );
    const page = sessionPage(
      sessionRows(data, this._query, this._sort, this._ascending),
      this._page,
      this._config.rows || 10,
    );
    this._page = page.index;
    const rows = page.items;
    const selected = this.selectedSession(data);
    const costEntityId = entity?.attributes.thor_card?.entities.last_session_cost;
    const currency =
      (costEntityId && this.hass?.states[costEntityId]?.attributes.unit_of_measurement) || '€';
    const greenTotal = sessionGreenTotalView(data, language);
    const fmt = (value: number | null) => formatSessionNumber(value, language);
    const fmtDate = (value: string | null | undefined) =>
      formatSessionDate(value, language, timeZone);
    const head = (key: SessionSort, label: string, cls = '') =>
      html`<th class=${cls}>
        <button @click=${() => this.sort(key)}>
          ${label}${this._sort === key ? (this._ascending ? ' ↑' : ' ↓') : ''}
        </button>
      </th>`;
    return html`<ha-card class="card ${dark ? 'dark' : ''}"
      ><header><h2>${this._config.name || t('title')}</h2></header>
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
      <div class="toolbar">
        <input
          class="search"
          type="search"
          .value=${this._query}
          aria-label=${t('search')}
          placeholder=${t('search')}
          @input=${(e: InputEvent) => {
            this.goToPage(0);
            this._query = (e.target as HTMLInputElement).value;
          }}
        />
      </div>
      ${this._config.show_curve === false
        ? nothing
        : html`<section class="curve">
            <div class="curve-title">
              ${t('chart')} · ${fmtDate(selected?.start_time)}
              ${selected?.active ? ` · ${t('active')}` : ''}
            </div>
            <div class="chart-area">
              <div class="chart" role="img" aria-label=${t('chart')} ${ref(this._chartRef)}></div>
              ${selected?.power_curve?.length
                ? nothing
                : html`<div class="no-curve">
                    ${this._details.status(selected?.session_id) === 'loading'
                      ? t('loadingCurve')
                      : this._details.status(selected?.session_id) === 'error'
                        ? t('curveLoadError')
                        : selected?.active
                          ? t('waitingCurve')
                          : t('noCurve')}
                  </div>`}
            </div>
            ${renderSessionEvents(selected?.events, language, dark, timeZone)}
          </section>`}
      ${selected ? renderSessionAccounting(selected, language, currency) : nothing}
      <div class="table-wrap" ${ref(this._tableRef)}>
        <table class="session-table">
          <thead>
            <tr>
              ${head('start', t('start'))}${head('end', t('end'), 'optional')}${head(
                'energy',
                t('energy'),
                'num',
              )}${head('green', t('green'), 'num optional')}${head('cost', t('cost'), 'num')}${this
                ._config.show_identifier === false
                ? nothing
                : head('identifier', t('identifier'))}
            </tr>
          </thead>
          <tbody>
            ${rows.length
              ? rows.map((row) => {
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
                    @click=${() => this.selectSession(row.session_id)}
                    @keydown=${(event: KeyboardEvent) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        this.selectSession(row.session_id);
                      }
                    }}
                  >
                    <td>
                      ${fmtDate(row.start_time)}
                      ${row.session_id
                        ? html`<small class="session-id">ID: ${row.session_id}</small>`
                        : nothing}
                      ${row.active
                        ? html`<span class="active-badge">${t('active')}</span>`
                        : nothing}
                    </td>
                    <td class="optional">${row.active ? t('active') : fmtDate(row.end_time)}</td>
                    <td class="num">
                      ${row.energy_source === 'power_fallback' ? '≈ ' : ''}${fmt(row.energy_kwh)}
                      kWh
                    </td>
                    <td class="num optional">${metrics.green}</td>
                    <td class="num">${metrics.cost}${metrics.costBasis}</td>
                    ${this._config.show_identifier === false
                      ? nothing
                      : html`<td>${renderSessionIdentifier(row)}</td>`}
                  </tr>`;
                })
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
          showIdentifier: this._config.show_identifier !== false,
          sort: this._sort,
          ascending: this._ascending,
          onSort: (key) => this.sort(key),
          onSelect: (id) => this.selectSession(id),
        })}
      </div>
      ${page.total
        ? html`<nav class="table-pagination" aria-label=${t('page')}>
            <span class="page-range">${page.from}–${page.to} / ${page.total}</span>
            <div class="page-controls">
              <button
                type="button"
                aria-label=${t('previousPage')}
                title=${t('previousPage')}
                ?disabled=${page.index === 0}
                @click=${() => this.goToPage(page.index - 1, true)}
              >
                ‹
              </button>
              <span aria-live="polite">${t('page')} ${page.index + 1} / ${page.count}</span>
              <button
                type="button"
                aria-label=${t('nextPage')}
                title=${t('nextPage')}
                ?disabled=${page.index >= page.count - 1}
                @click=${() => this.goToPage(page.index + 1, true)}
              >
                ›
              </button>
            </div>
          </nav>`
        : nothing}</ha-card
    >`;
  }
}
if (!customElements.get('growatt-thor-session-card'))
  customElements.define('growatt-thor-session-card', ThorSessionCard);
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === 'growatt-thor-session-card'))
  window.customCards.push({
    type: 'growatt-thor-session-card',
    name: 'Growatt THOR Sessions',
    preview: true,
    description: 'Charging history, KPIs and energy chart. / Ladehistorie, KPIs und Energiekurve.',
    documentationURL: 'https://github.com/bobbesnl/growatt_thor#growatt-thor-dashboard-card',
    getEntitySuggestion: (hass: Hass, id: string) =>
      hass.states[id]?.attributes.thor_card?.sessions?.schema === 1
        ? {
            config: {
              type: 'custom:growatt-thor-session-card',
              entity: id,
              entry_id: hass.states[id]?.attributes.thor_card?.entry_id,
            },
          }
        : null,
  });
