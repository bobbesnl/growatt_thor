import type { SessionItem } from '../shared/types';
import { sessionTranslate } from './locales';
import {
  sessionChartPoints,
  sessionContextPoints,
  sessionEventMarkers,
  sessionChartBreaks,
  sessionChartSpansDaysInZone,
  sessionChartExtent,
  type SessionEventMarker,
  type SessionChartBreak,
} from './model';

const WATTS_PER_KILOWATT = 1000;

type ContextPoints = [number, number | null][];
export interface SessionChartModel {
  points: [number, number][];
  measuredCurrents: ContextPoints;
  configuredCurrents: ContextPoints;
  pvSurplus: ContextPoints;
  houseLoad: ContextPoints;
  batteryFlow: ContextPoints;
  markers: SessionEventMarker[];
  eventHost: string;
  eventLayerVisible: boolean;
  reducedMotion: boolean;
  fadeEventLabels: boolean;
  dark: boolean;
  compact: boolean;
  language: string;
  timeZone: string;
  chartSpansDays: boolean;
  powerAxisVisible: boolean;
  currentAxisVisible: boolean;
  extent?: [number, number];
  chartBreaks: (SessionChartBreak & { gap: string; isExpanded: boolean })[];
  legendSelected: Record<string, boolean>;
  zoomRange: { start: number; end: number };
  powerSeriesName: string;
  pvSurplusSeriesName: string;
  houseLoadSeriesName: string;
  batteryFlowSeriesName: string;
  configuredCurrentSeriesName: string;
  measuredCurrentSeriesName: string;
  eventSeriesName: string;
}

interface SessionChartInputs {
  legendSelected: Record<string, boolean>;
  expandedBreaks: ReadonlySet<string>;
  zoomRange: { start: number; end: number };
  previousEventLabelFadeKey?: string;
  language: string;
  timeZone: string;
  compact: boolean;
  reducedMotion: boolean;
  dark: boolean;
}

/** Derive chart data and the next fade key without changing the card's state. */
export function deriveSessionChartModel(
  session: SessionItem | undefined,
  {
    legendSelected,
    expandedBreaks,
    zoomRange,
    previousEventLabelFadeKey,
    language,
    timeZone,
    compact,
    reducedMotion,
    dark,
  }: SessionChartInputs,
) {
  const points = sessionChartPoints(session?.power_curve || []);
  const measuredCurrents = sessionContextPoints(session?.measured_current_sum_curve_a);
  const configuredCurrents = sessionContextPoints(session?.configured_current_limit_curve_a);
  const pvSurplus = sessionContextPoints(session?.site_pv_surplus_curve_w, WATTS_PER_KILOWATT);
  const houseLoad = sessionContextPoints(session?.site_house_load_curve_w, WATTS_PER_KILOWATT);
  const batteryFlow = sessionContextPoints(session?.site_battery_curve_w, WATTS_PER_KILOWATT, true);
  if (
    !points.length &&
    !measuredCurrents.length &&
    !configuredCurrents.length &&
    !pvSurplus.length &&
    !houseLoad.length &&
    !batteryFlow.length
  ) {
    return;
  }
  const t = sessionTranslate(language);
  const markers = sessionEventMarkers(session?.events);
  const chartSeries = [measuredCurrents, configuredCurrents, pvSurplus, houseLoad, batteryFlow];
  const chartBreaks = sessionChartBreaks(points, markers, ...chartSeries).map((axisBreak) => ({
    ...axisBreak,
    gap: '5%',
    isExpanded: expandedBreaks.has(`${axisBreak.start}:${axisBreak.end}`),
  }));
  const chartSpansDays = sessionChartSpansDaysInZone(timeZone, points, markers, ...chartSeries);
  const powerSeriesName = t('seriesPower');
  const measuredCurrentSeriesName = t('seriesMeasuredCurrentSum');
  const configuredCurrentSeriesName = t('seriesConfiguredCurrentLimit');
  const pvSurplusSeriesName = t('seriesPvSurplus');
  const houseLoadSeriesName = `${['site_balance', 'mixed'].includes(session?.site_house_load_source || '') ? '≈ ' : ''}${t('seriesHouseLoad')}`;
  const batteryFlowSeriesName = t('seriesBatteryFlow');
  const eventSeriesName = t('seriesEvents');
  const powerVisible = legendSelected[powerSeriesName] !== false;
  const pvSurplusVisible = legendSelected[pvSurplusSeriesName] !== false;
  const houseLoadVisible = legendSelected[houseLoadSeriesName] !== false;
  const batteryFlowVisible = legendSelected[batteryFlowSeriesName] !== false;
  const measuredCurrentVisible = legendSelected[measuredCurrentSeriesName] !== false;
  const configuredCurrentVisible = legendSelected[configuredCurrentSeriesName] !== false;
  const powerAxisVisible =
    (powerVisible && !!points.length) ||
    (pvSurplusVisible && !!pvSurplus.length) ||
    (houseLoadVisible && !!houseLoad.length) ||
    (batteryFlowVisible && !!batteryFlow.length);
  const currentAxisVisible =
    (measuredCurrentVisible && !!measuredCurrents.length) ||
    (configuredCurrentVisible && !!configuredCurrents.length);
  const eventLayerVisible = !compact && legendSelected[eventSeriesName] !== false;
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
    previousEventLabelFadeKey !== fadeKey;
  const eventLabelFadeKey = !eventLayerVisible
    ? undefined
    : fadeEventLabels
      ? fadeKey
      : previousEventLabelFadeKey;
  const model: SessionChartModel = {
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
    legendSelected: legendSelected,
    zoomRange: zoomRange,
    powerSeriesName,
    pvSurplusSeriesName,
    houseLoadSeriesName,
    batteryFlowSeriesName,
    configuredCurrentSeriesName,
    measuredCurrentSeriesName,
    eventSeriesName,
  };
  return { model, fadeKey, eventLabelFadeKey };
}
