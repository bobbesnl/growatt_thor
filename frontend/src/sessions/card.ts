import { renderSessionAccounting } from './accounting.template';
import { cardInitialization } from '../shared/card-initialization';
import { cardNoticeStyles, renderCardNotice } from '../shared/card-notice';
import { sessionMetricViews } from './metrics.template';
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
  formatSessionChartTick,
  formatSessionNumber,
  sessionChartBreaks,
  sessionChartExtent,
  sessionChartPoints,
  sessionChartSpansDays,
  sessionEventMarkers,
  sessionNumericPoints,
  selectedSession,
  sessionSignedChartPoints,
  sessionRows,
  sessionPage,
  type SessionSort,
} from './model';
import { sessionTranslate } from './locales';
import { renderSessionList } from './list.template';
import {
  renderSessionEvents,
  sessionEventLabel,
  sessionEventColors,
  sessionEventReason,
} from './events.template';
import { SessionDetailStore } from './detail-store';
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
  static styles = [unsafeCSS(cssText), cardNoticeStyles];
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
  private _chart?: echarts.ECharts;
  private _legendSelected: Record<string, boolean> = {};
  private _dataZoomRange = { start: 0, end: 100 };
  private _expandedBreaks = new Set<string>();
  private _chartSessionKey?: string;
  private _eventLabelFadeKey?: string;
  private _labelFadeFrame?: number;
  private _chartRef: Ref<HTMLDivElement> = createRef();
  private _tableRef: Ref<HTMLDivElement> = createRef();
  private _resizeObserver?: ResizeObserver;
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
    this._resizeObserver?.disconnect();
    if (this._labelFadeFrame !== undefined) cancelAnimationFrame(this._labelFadeFrame);
    this._chart?.dispose();
    this._chart = undefined;
  }
  firstUpdated() {
    this._resizeObserver = new ResizeObserver(() => {
      this._chart?.resize();
      // Recompute label density and event placement for dashboard-column changes,
      // not only viewport changes. drawChart retains the current zoom and legend.
      this.drawChart();
    });
    if (this._chartRef.value) this._resizeObserver.observe(this._chartRef.value);
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
    if (!el || !data || this._config.show_curve === false) return;
    if (!this._chart) {
      this._chart = echarts.init(el);
      this._chart.on('legendselectchanged', (event: unknown) => {
        const selected = (event as { selected?: Record<string, boolean> }).selected;
        this._legendSelected = { ...(selected || {}) };
        this.drawChart();
      });
      this._chart.on('datazoom', (event: unknown) => {
        const zoomEvent = event as {
          start?: number;
          end?: number;
          batch?: Array<{ start?: number; end?: number }>;
        };
        const range = zoomEvent.batch?.[0] || zoomEvent;
        if (Number.isFinite(range.start) && Number.isFinite(range.end))
          this._dataZoomRange = { start: range.start!, end: range.end! };
      });
      this._chart.on('axisbreakchanged', (event: unknown) => {
        const breaks = (
          event as { breaks?: Array<{ start: unknown; end: unknown; isExpanded: boolean }> }
        ).breaks;
        for (const axisBreak of breaks || []) {
          const key = `${axisBreak.start}:${axisBreak.end}`;
          if (axisBreak.isExpanded) this._expandedBreaks.add(key);
          else this._expandedBreaks.delete(key);
        }
      });
    }
    const dark =
      this._config.theme === 'dark' ||
      (this._config.theme !== 'light' && !!this.hass?.themes?.darkMode);
    const compact = this.clientWidth <= 600;
    const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const session = this.selectedSession(data);
    const sessionKey = session?.session_id || `${session?.start_time || 'unknown'}`;
    if (this._chartSessionKey !== sessionKey) {
      this._chartSessionKey = sessionKey;
      this._dataZoomRange = { start: 0, end: 100 };
      this._expandedBreaks.clear();
    }
    const points = sessionChartPoints(session?.power_curve || []);
    const measuredCurrents = sessionNumericPoints(session?.measured_current_sum_curve_a);
    const configuredCurrents = sessionNumericPoints(session?.configured_current_limit_curve_a);
    const pvSurplus = sessionChartPoints(session?.site_pv_surplus_curve_w || []);
    const houseLoad = sessionChartPoints(session?.site_house_load_curve_w || []);
    const batteryFlow = sessionSignedChartPoints(session?.site_battery_curve_w);
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
    const language = this.hass?.language || this.hass?.locale?.language || 'en';
    const t = sessionTranslate(language);
    const markers = sessionEventMarkers(session?.events);
    const chartSeries = [measuredCurrents, configuredCurrents, pvSurplus, houseLoad, batteryFlow];
    const chartBreaks = sessionChartBreaks(points, markers, ...chartSeries).map((axisBreak) => ({
      ...axisBreak,
      gap: '5%',
      isExpanded: this._expandedBreaks.has(`${axisBreak.start}:${axisBreak.end}`),
    }));
    const chartSpansDays = sessionChartSpansDays(points, markers, ...chartSeries);
    const powerSeriesName = t('seriesPower');
    const measuredCurrentSeriesName = t('seriesMeasuredCurrentSum');
    const configuredCurrentSeriesName = t('seriesConfiguredCurrentLimit');
    const pvSurplusSeriesName = t('seriesPvSurplus');
    const houseLoadSeriesName = t('seriesHouseLoad');
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
    const palette = {
      charge: '#8bc53f',
      solar: dark ? '#a5da69' : '#8bc53f',
      target: dark ? '#79c7f2' : '#2f7fb8',
      house: dark ? '#efbe6b' : '#b36f14',
      battery: dark ? '#b9a9f4' : '#7564b5',
      measuredCurrent: dark ? '#a5da69' : '#3f7510',
      neutral: dark ? '#a4b3a6' : '#6c7b72',
    };
    const markerColors = sessionEventColors(dark);
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
    const eventMarkLine = (labelOpacity: number) =>
      eventLayerVisible
        ? {
            animation: !reducedMotion,
            animationDuration: 0,
            animationDurationUpdate: 240,
            animationEasingUpdate: 'cubicOut' as const,
            silent: false,
            symbol: ['none', 'none'],
            data: markers.map((marker) => {
              const color = markerColors[marker.tone];
              const types = marker.events.map((event) => event.type);
              const label = sessionEventLabel(types, marker.provisional, language);
              const reason = sessionEventReason(
                marker.events.map((event) => event.reason).find(Boolean),
                language,
              );
              return {
                name: label,
                xAxis: marker.at,
                lineStyle: {
                  color,
                  type: marker.provisional ? ('dashed' as const) : ('solid' as const),
                  width: 1.5,
                },
                label: {
                  show: true,
                  formatter: label,
                  position: 'insideEndTop',
                  rotate: 90,
                  align: 'center',
                  verticalAlign: 'middle',
                  offset: [0, 4],
                  color: marker.tone === 'lime' ? '#172019' : '#fff',
                  backgroundColor: color,
                  padding: [3, 6],
                  borderRadius: 4,
                  fontSize: 10,
                  fontWeight: 700,
                  opacity: labelOpacity,
                },
                tooltip: {
                  formatter: [label, new Date(marker.at).toLocaleString(language), reason]
                    .filter(Boolean)
                    .join('<br>'),
                },
              };
            }),
          }
        : undefined;
    const initialEventMarkLine = eventMarkLine(fadeEventLabels ? 0 : 1);
    this._chart.setOption(
      {
        animation: !reducedMotion,
        legend: {
          bottom: 0,
          left: 'center',
          type: 'scroll',
          data: [
            points.length && powerSeriesName,
            pvSurplus.length && pvSurplusSeriesName,
            houseLoad.length && houseLoadSeriesName,
            batteryFlow.length && batteryFlowSeriesName,
            configuredCurrents.length && configuredCurrentSeriesName,
            measuredCurrents.length && measuredCurrentSeriesName,
            !compact && eventSeriesName,
          ].filter(Boolean),
          selected: this._legendSelected,
          textStyle: { color: dark ? '#d7dfd8' : '#34423a', fontSize: 10 },
        },
        dataZoom: [
          {
            type: 'inside',
            xAxisIndex: 0,
            start: this._dataZoomRange.start,
            end: this._dataZoomRange.end,
            filterMode: 'none',
            zoomOnMouseWheel: 'shift',
            moveOnMouseMove: true,
            moveOnMouseWheel: false,
          },
          {
            type: 'slider',
            xAxisIndex: 0,
            start: this._dataZoomRange.start,
            end: this._dataZoomRange.end,
            filterMode: 'none',
            bottom: 36,
            height: 16,
            showDetail: false,
            showDataShadow: 'auto',
            backgroundColor: dark ? 'rgba(52,64,57,.32)' : 'rgba(229,235,227,.45)',
            borderColor: dark ? '#506057' : '#d3ddd1',
            fillerColor: dark ? 'rgba(139,197,63,.24)' : 'rgba(139,197,63,.20)',
            dataBackground: {
              lineStyle: { color: dark ? '#738078' : '#9ba89f', opacity: 0.45 },
              areaStyle: { color: dark ? '#3b4840' : '#dce4da', opacity: 0.3 },
            },
            selectedDataBackground: {
              lineStyle: { color: palette.charge, opacity: 0.85 },
              areaStyle: { color: palette.charge, opacity: 0.16 },
            },
            handleSize: 12,
            handleStyle: {
              color: dark ? '#212d25' : '#fff',
              borderColor: palette.charge,
              borderWidth: 1.5,
            },
            moveHandleStyle: { color: palette.charge, opacity: 0.7 },
            brushSelect: true,
          },
        ],
        grid: { left: 40, right: currentAxisVisible ? 40 : 16, top: compact ? 24 : 48, bottom: 88 },
        tooltip: { trigger: 'axis', confine: true },
        xAxis: {
          type: 'time',
          splitNumber: Math.max(
            2,
            Math.min(8, Math.floor((el.clientWidth - 80) / (chartSpansDays ? 140 : 110))),
          ),
          min: extent?.[0],
          max: extent?.[1],
          breaks: chartBreaks,
          breakArea: {
            show: true,
            expandOnClick: true,
            zigzagAmplitude: 3,
            zigzagMinSpan: 4,
            zigzagMaxSpan: 10,
            itemStyle: {
              color: dark ? 'rgba(24,33,29,.88)' : 'rgba(255,255,255,.9)',
              borderColor: dark ? '#a4b3a6' : '#65756b',
              borderWidth: 1,
              opacity: 0.9,
            },
          },
          axisLabel: {
            hideOverlap: true,
            fontSize: compact ? 11 : 12,
            color: dark ? '#a4b3a6' : '#65756b',
            formatter: (value: number) => formatSessionChartTick(value, language, chartSpansDays),
          },
          axisTick: { show: false },
          axisLine: { lineStyle: { color: dark ? '#344039' : '#e5ebe3' } },
        },
        yAxis: [
          {
            type: 'value',
            name: 'kW',
            show: powerAxisVisible,
            splitNumber: 3,
            nameTextStyle: { color: dark ? '#a4b3a6' : '#65756b' },
            axisLabel: { color: dark ? '#a4b3a6' : '#65756b' },
            splitLine: { lineStyle: { color: dark ? '#344039' : '#e5ebe3' } },
          },
          {
            type: 'value',
            name: 'A',
            show: currentAxisVisible,
            splitNumber: 3,
            nameTextStyle: { color: dark ? '#a4b3a6' : '#65756b' },
            axisLabel: { color: dark ? '#a4b3a6' : '#65756b' },
            axisLine: { show: true, lineStyle: { color: dark ? '#344039' : '#e5ebe3' } },
            splitLine: { show: false },
          },
        ],
        series: [
          {
            name: powerSeriesName,
            id: 'power',
            type: 'line',
            yAxisIndex: 0,
            data: points,
            smooth: 0.25,
            showSymbol: false,
            symbolSize: 5,
            lineStyle: { width: 3, color: palette.charge },
            itemStyle: { color: palette.charge },
            areaStyle: { color: dark ? 'rgba(139,197,63,.16)' : 'rgba(139,197,63,.20)' },
            z: 4,
            markLine: eventHost === 'power' ? initialEventMarkLine : undefined,
          },
          {
            name: pvSurplusSeriesName,
            id: 'pv',
            type: 'line',
            yAxisIndex: 0,
            data: pvSurplus,
            smooth: 0.22,
            showSymbol: false,
            symbolSize: 3,
            lineStyle: { width: 2, color: palette.solar, type: 'dashed' },
            itemStyle: { color: palette.solar },
            z: 3,
            markLine: eventHost === 'pv' ? initialEventMarkLine : undefined,
          },
          {
            name: houseLoadSeriesName,
            id: 'house',
            type: 'line',
            yAxisIndex: 0,
            data: houseLoad,
            smooth: 0.18,
            showSymbol: false,
            symbolSize: 3,
            lineStyle: { width: 1.6, color: palette.house, opacity: 0.82 },
            itemStyle: { color: palette.house },
            z: 2,
            markLine: eventHost === 'house' ? initialEventMarkLine : undefined,
          },
          {
            name: batteryFlowSeriesName,
            id: 'battery',
            type: 'line',
            yAxisIndex: 0,
            data: batteryFlow,
            smooth: 0.18,
            showSymbol: false,
            symbolSize: 3,
            lineStyle: { width: 1.8, color: palette.battery },
            itemStyle: { color: palette.battery },
            z: 3,
            markLine: eventHost === 'battery' ? initialEventMarkLine : undefined,
          },
          {
            name: measuredCurrentSeriesName,
            id: 'measured-current',
            type: 'line',
            yAxisIndex: 1,
            data: measuredCurrents,
            smooth: 0.2,
            showSymbol: false,
            symbolSize: 4,
            lineStyle: { width: 2, color: palette.measuredCurrent },
            itemStyle: { color: palette.measuredCurrent },
            z: 3,
            markLine: eventHost === 'measured-current' ? initialEventMarkLine : undefined,
          },
          {
            name: configuredCurrentSeriesName,
            id: 'configured-current',
            type: 'line',
            yAxisIndex: 1,
            data: configuredCurrents,
            smooth: 0.25,
            showSymbol: false,
            symbolSize: 3,
            lineStyle: { width: 1.5, color: palette.target, opacity: 0.55 },
            itemStyle: { color: palette.target, opacity: 0.6 },
            emphasis: { lineStyle: { width: 2, opacity: 0.85 } },
            z: 1,
            markLine: eventHost === 'configured-current' ? initialEventMarkLine : undefined,
          },
          {
            name: eventSeriesName,
            id: 'events',
            type: 'line',
            yAxisIndex: 0,
            data: points,
            symbol: 'none',
            lineStyle: { opacity: 0 },
            itemStyle: { color: palette.neutral },
            tooltip: { show: false },
            z: 6,
            markLine: eventHost === 'events' ? initialEventMarkLine : undefined,
          },
        ],
      },
      { notMerge: true },
    );
    if (this._labelFadeFrame !== undefined) cancelAnimationFrame(this._labelFadeFrame);
    if (fadeEventLabels) {
      this._labelFadeFrame = requestAnimationFrame(() => {
        this._labelFadeFrame = requestAnimationFrame(() => {
          if (this._eventLabelFadeKey !== fadeKey) return;
          this._chart?.setOption({
            animationDurationUpdate: 240,
            animationEasingUpdate: 'cubicOut',
            series: [{ id: eventHost, markLine: eventMarkLine(1) }],
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
  private goToPage(index: number) {
    this._page = index;
    if (this._tableRef.value) this._tableRef.value.scrollTop = 0;
    this.requestUpdate();
  }
  private selectSession(sessionId: string | null) {
    this._selectedSessionId = sessionId || undefined;
    this._details.retry(sessionId);
    this._chartSessionKey = undefined;
  }
  render() {
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
    const fmt = (value: number | null) => formatSessionNumber(value, language);
    const fmtDate = (value: string | null | undefined) => formatSessionDate(value, language);
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
          <span>${t('green')}</span><strong>${fmt(data.total_green_energy_kwh)} kWh</strong>
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
            ${renderSessionEvents(selected?.events, language, dark)}
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
                      : html`<td>${row.authorized_identifier || '—'}</td>`}
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
                @click=${() => this.goToPage(page.index - 1)}
              >
                ‹
              </button>
              <span aria-live="polite">${t('page')} ${page.index + 1} / ${page.count}</span>
              <button
                type="button"
                aria-label=${t('nextPage')}
                title=${t('nextPage')}
                ?disabled=${page.index >= page.count - 1}
                @click=${() => this.goToPage(page.index + 1)}
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
