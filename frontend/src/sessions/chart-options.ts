import { sessionEventLabel, sessionEventColors, sessionEventReason } from './events.template';
import { formatSessionChartTick, type SessionEventMarker, type SessionChartBreak } from './model';
import type { chartPalette } from '../shared/palette';

export const SESSION_COMPACT_WIDTH_PX = 600;
export const CHART_ANIMATION_MS = 240;
export const WATTS_PER_KILOWATT = 1000;
const CHART_HORIZONTAL_SPACE_PX = 80;
const MULTIDAY_TICK_WIDTH_PX = 140;
const INTRADAY_TICK_WIDTH_PX = 110;

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

export function buildSessionEventMarkLine(model: SessionChartModel, labelOpacity: number) {
  const { eventLayerVisible, reducedMotion, markers, language, timeZone, dark } = model;
  const markerColors = sessionEventColors(dark);
  return eventLayerVisible
    ? {
        animation: !reducedMotion,
        animationDuration: 0,
        animationDurationUpdate: CHART_ANIMATION_MS,
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
              formatter: [label, new Date(marker.at).toLocaleString(language, { timeZone }), reason]
                .filter(Boolean)
                .join('<br>'),
            },
          };
        }),
      }
    : undefined;
}

export function buildSessionChartOption(
  model: SessionChartModel,
  palette: ReturnType<typeof chartPalette>,
  width: number,
) {
  const {
    points,
    measuredCurrents,
    configuredCurrents,
    pvSurplus,
    houseLoad,
    batteryFlow,
    eventHost,
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
    legendSelected,
    zoomRange,
    powerSeriesName,
    pvSurplusSeriesName,
    houseLoadSeriesName,
    batteryFlowSeriesName,
    configuredCurrentSeriesName,
    measuredCurrentSeriesName,
    eventSeriesName,
  } = model;
  const initialEventMarkLine = buildSessionEventMarkLine(model, fadeEventLabels ? 0 : 1);
  return {
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
      selected: legendSelected,
      textStyle: { color: palette.text, fontSize: 10 },
    },
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: 0,
        start: zoomRange.start,
        end: zoomRange.end,
        filterMode: 'none',
        zoomOnMouseWheel: 'shift',
        moveOnMouseMove: true,
        moveOnMouseWheel: false,
      },
      {
        type: 'slider',
        xAxisIndex: 0,
        start: zoomRange.start,
        end: zoomRange.end,
        filterMode: 'none',
        bottom: 36,
        height: 16,
        showDetail: false,
        showDataShadow: 'auto',
        backgroundColor: palette.zoomBackground,
        borderColor: palette.zoomBorder,
        fillerColor: palette.zoomFill,
        dataBackground: {
          lineStyle: { color: palette.shadowLine, opacity: 0.45 },
          areaStyle: { color: palette.shadowArea, opacity: 0.3 },
        },
        selectedDataBackground: {
          lineStyle: { color: palette.charge, opacity: 0.85 },
          areaStyle: { color: palette.charge, opacity: 0.16 },
        },
        handleSize: 12,
        handleStyle: {
          color: dark ? palette.panel : palette.surface,
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
        Math.min(
          8,
          Math.floor(
            (width - CHART_HORIZONTAL_SPACE_PX) /
              (chartSpansDays ? MULTIDAY_TICK_WIDTH_PX : INTRADAY_TICK_WIDTH_PX),
          ),
        ),
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
          borderColor: palette.muted,
          borderWidth: 1,
          opacity: 0.9,
        },
      },
      axisLabel: {
        hideOverlap: true,
        fontSize: compact ? 11 : 12,
        color: palette.muted,
        formatter: (value: number) =>
          formatSessionChartTick(value, language, chartSpansDays, timeZone),
      },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: palette.line } },
    },
    yAxis: [
      {
        type: 'value',
        name: 'kW',
        show: powerAxisVisible,
        splitNumber: 3,
        nameTextStyle: { color: palette.muted },
        axisLabel: { color: palette.muted },
        splitLine: { lineStyle: { color: palette.line } },
      },
      {
        type: 'value',
        name: 'A',
        show: currentAxisVisible,
        splitNumber: 3,
        nameTextStyle: { color: palette.muted },
        axisLabel: { color: palette.muted },
        axisLine: { show: true, lineStyle: { color: palette.line } },
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
        areaStyle: { color: palette.area },
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
        step: 'end',
        type: 'line',
        yAxisIndex: 1,
        data: configuredCurrents,
        smooth: false,
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
  };
}
