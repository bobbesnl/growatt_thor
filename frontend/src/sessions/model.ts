import { elapsed, numeric } from '../shared/model';
import type {
  CardData,
  Entity,
  Hass,
  SessionEvent,
  SessionEventType,
  SessionHistoryData,
  SessionItem,
} from '../shared/types';

const EVENT_TYPES = new Set<SessionEventType>([
  'plugged_in',
  'transaction_started',
  'energy_flow_started',
  'charging_paused',
  'energy_flow_stopped',
  'stop_requested',
  'transaction_stopped',
  'unplugged',
]);

export type SessionEventTone = 'lime' | 'blue' | 'amber' | 'coral' | 'neutral';
export interface SessionEventMarker {
  at: number;
  events: SessionEvent[];
  tone: SessionEventTone;
  provisional: boolean;
}

export interface SessionChartBreak {
  start: number;
  end: number;
}

const MIN_CHART_BREAK_MS = 4 * 60 * 60 * 1000;
const CHART_BREAK_CONTEXT_MS = 15 * 60 * 1000;
const MAX_CHART_BREAKS = 3;

/** Reject malformed or unbalanced accounting without changing old session rows. */
export function sessionAccountingSummary(row: SessionItem) {
  const sources = row.source_energy_kwh;
  if (!sources || row.energy_kwh === null || !Number.isFinite(row.energy_kwh)) return null;
  const values = [
    sources.direct_solar,
    sources.direct_grid,
    sources.battery_unknown,
    sources.unknown,
  ];
  if (values.some((value) => !Number.isFinite(value) || value < 0)) return null;
  if (Math.abs(values.reduce((sum, value) => sum + value, 0) - row.energy_kwh) > 0.001) return null;
  return {
    sources,
    cost: row.effective_grid_cost ?? null,
    coverage: row.accounting_coverage ?? null,
    quality: row.accounting_quality ?? null,
    policy: row.accounting_policy ?? null,
  };
}

export function sessionTimestamp(value: string): number | null {
  const timestamp = Date.parse(value.replace(' ', 'T'));
  return Number.isFinite(timestamp) ? timestamp : null;
}

/** Hide empty categories without turning missing source or price data into zero. */
export function sessionEnergyBreakdown(row: SessionItem) {
  const accounting = sessionAccountingSummary(row);
  if (!accounting) return null;
  const sources = accounting.sources;
  const total = row.energy_kwh!;
  const parts = (
    [
      ['solar', sources.direct_solar],
      ['battery', sources.battery_unknown],
      ['grid', sources.direct_grid],
      ['unknown', sources.unknown],
    ] as const
  )
    .filter(([, value]) => value > 1e-9)
    .map(([label, kwh]) => ({
      label,
      kwh,
      share: total > 0 ? (kwh / total) * 100 : 0,
    }));
  const known = sources.direct_solar + sources.battery_unknown + sources.direct_grid;
  return {
    parts,
    unknown: sources.unknown > 1e-9 ? sources.unknown : 0,
    fullyUnknown: total > 0 && known === 0,
    coverage: total > 0 ? (known / total) * 100 : 0,
    hasBattery: sources.battery_unknown > 0,
    policy: accounting.policy?.id,
    // Zero remains a valid tariff result, but no allocation cannot prove free charging.
    cost:
      known > 0 && accounting.cost !== null && Number.isFinite(accounting.cost)
        ? accounting.cost
        : null,
  };
}

/** Accounting remains authoritative after stop; missing prices never become flat-rate costs. */
export function sessionRowMetrics(row: SessionItem) {
  const breakdown = sessionEnergyBreakdown(row);
  const useGridCost = row.source_energy_kwh != null;
  const reportedGreen = row.green_energy_kwh;
  const validGreen = reportedGreen !== null && Number.isFinite(reportedGreen) && reportedGreen >= 0;
  const knownSources = !!breakdown && !breakdown.fullyUnknown && row.energy_kwh! > 0;
  const solar = knownSources
    ? (breakdown.parts.find((part) => part.label === 'solar')?.kwh ?? 0)
    : null;
  return {
    green: validGreen ? reportedGreen : solar,
    greenPartial: !validGreen && knownSources && breakdown!.unknown > 0,
    unknown: breakdown?.unknown ?? 0,
    cost: useGridCost ? (breakdown?.cost ?? null) : row.cost,
    costIsGrid: useGridCost,
    costPartial: useGridCost && (breakdown?.unknown ?? 0) > 0,
  };
}

export function sessionChartPoints(points: [string, number][]): [number, number][] {
  return sessionNumericPoints(points, 1000);
}

export function sessionSignedChartPoints(points: [string, number][] = []): [number, number][] {
  return points.flatMap(([at, watts]) => {
    const timestamp = sessionTimestamp(at);
    return timestamp === null || !Number.isFinite(watts)
      ? []
      : [[timestamp, watts / 1000] as [number, number]];
  });
}

export function sessionNumericPoints(
  points: [string, number][] = [],
  divisor = 1,
): [number, number][] {
  return points.flatMap(([at, watts]) => {
    const timestamp = sessionTimestamp(at);
    return timestamp === null || !Number.isFinite(watts) || watts < 0 || divisor <= 0
      ? []
      : [[timestamp, watts / divisor] as [number, number]];
  });
}

export function sessionEventTone(events: SessionEvent[]): SessionEventTone {
  const types = new Set(events.map((event) => event.type));
  if (types.has('stop_requested')) return 'coral';
  if (types.has('energy_flow_stopped') || types.has('charging_paused')) return 'amber';
  if (types.has('energy_flow_started')) return 'lime';
  if (types.has('transaction_started')) return 'blue';
  return 'neutral';
}

export function sessionEventMarkers(events: SessionEvent[] = []): SessionEventMarker[] {
  const valid = events
    .flatMap((event) => {
      const at = sessionTimestamp(event.at);
      return at === null || !EVENT_TYPES.has(event.type) ? [] : [{ at, event }];
    })
    .sort((a, b) => a.at - b.at);
  const groups: Array<{ at: number; events: SessionEvent[] }> = [];
  for (const item of valid) {
    const previous = groups.at(-1);
    if (previous && item.at - previous.at <= 30_000) previous.events.push(item.event);
    else groups.push({ at: item.at, events: [item.event] });
  }
  return groups.map(({ at, events: groupedEvents }) => ({
    at,
    events: groupedEvents,
    tone: sessionEventTone(groupedEvents),
    provisional: groupedEvents.some((event) => event.certainty === 'provisional'),
  }));
}

export function sessionChartExtent(
  points: [number, number][],
  markers: SessionEventMarker[],
  ...additionalSeries: [number, number][][]
): [number, number] | undefined {
  const timestamps = sessionChartTimestamps(points, markers, ...additionalSeries);
  if (!timestamps.length) return undefined;
  const minimum = Math.min(...timestamps);
  const maximum = Math.max(...timestamps);
  const padding = Math.max((maximum - minimum) * 0.035, 60_000);
  return [minimum - padding, maximum + padding];
}

function sessionChartTimestamps(
  points: [number, number][],
  markers: SessionEventMarker[],
  ...additionalSeries: [number, number][][]
): number[] {
  return Array.from(
    new Set(
      [points, ...additionalSeries]
        .flatMap((series) => series.map(([at]) => at))
        .concat(markers.map((marker) => marker.at))
        .filter(Number.isFinite),
    ),
  ).sort((a, b) => a - b);
}

/** Compress only long intervals that contain no samples or event boundaries. */
export function sessionChartBreaks(
  points: [number, number][],
  markers: SessionEventMarker[],
  ...additionalSeries: [number, number][][]
): SessionChartBreak[] {
  const timestamps = sessionChartTimestamps(points, markers, ...additionalSeries);
  return timestamps
    .slice(1)
    .map((end, index) => ({
      previous: timestamps[index],
      next: end,
      duration: end - timestamps[index],
    }))
    .filter(({ duration }) => duration >= MIN_CHART_BREAK_MS)
    .sort((a, b) => b.duration - a.duration)
    .slice(0, MAX_CHART_BREAKS)
    .map(({ previous, next, duration }) => {
      const context = Math.min(CHART_BREAK_CONTEXT_MS, duration * 0.1);
      return { start: previous + context, end: next - context };
    })
    .sort((a, b) => a.start - b.start);
}

export function sessionChartSpansDays(
  points: [number, number][],
  markers: SessionEventMarker[],
  ...additionalSeries: [number, number][][]
): boolean {
  const timestamps = sessionChartTimestamps(points, markers, ...additionalSeries);
  if (timestamps.length < 2) return false;
  const first = new Date(timestamps[0]);
  const last = new Date(timestamps.at(-1)!);
  return (
    first.getFullYear() !== last.getFullYear() ||
    first.getMonth() !== last.getMonth() ||
    first.getDate() !== last.getDate()
  );
}

export function entityNumber(entity?: Pick<Entity, 'state'>): number | null {
  if (!entity || ['unknown', 'unavailable', ''].includes(entity.state)) return null;
  return numeric(Number(entity.state));
}

export function formatSessionNumber(
  value: number | null,
  language?: string,
  maximumFractionDigits = 2,
): string {
  return value === null ? '—' : value.toLocaleString(language, { maximumFractionDigits });
}

export function formatSessionDate(value: string | null | undefined, language?: string): string {
  if (!value) return '—';
  const timestamp = sessionTimestamp(value);
  if (timestamp === null) return '—';
  return new Intl.DateTimeFormat(language, {
    weekday: 'short',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(timestamp);
}

/** Collapse only matching local calendar days, never an overnight session's dates. */
export function formatSessionPeriod(
  start: string | null | undefined,
  end: string | null | undefined,
  language?: string,
): { day: string | null; start: string; end: string } {
  const from = start ? sessionTimestamp(start) : null;
  const to = end ? sessionTimestamp(end) : null;
  if (
    from !== null &&
    (!end || (to !== null && new Date(from).toDateString() === new Date(to).toDateString()))
  ) {
    const time = new Intl.DateTimeFormat(language, { hour: '2-digit', minute: '2-digit' });
    return {
      day: new Intl.DateTimeFormat(language, {
        weekday: 'long',
        year: 'numeric',
        month: 'numeric',
        day: 'numeric',
      }).format(from),
      start: time.format(from),
      end: to === null ? '—' : time.format(to),
    };
  }
  return {
    day: null,
    start: formatSessionDate(start, language),
    end: formatSessionDate(end, language),
  };
}

export function formatSessionChartTick(
  timestamp: number,
  language: string | undefined,
  spansDays: boolean,
): string {
  if (!Number.isFinite(timestamp)) return '';
  const date = new Date(timestamp);
  const time = new Intl.DateTimeFormat(language, {
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
  if (!spansDays) return time;
  const weekday = new Intl.DateTimeFormat(language, { weekday: 'short' }).format(date);
  return `${weekday}\n${time}`;
}

export function storedSessionDuration(entity?: Entity): string {
  const value = entityNumber(entity);
  if (value === null) return '—';
  const minutes = Math.floor(value * (entity?.attributes.unit_of_measurement === 'min' ? 1 : 60));
  const hours = Math.floor(minutes / 60);
  return `${String(hours).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
}

export function sessionDisplay(hass: Hass, data: CardData, now: number) {
  const lastCost = hass.states[data.entities?.last_session_cost];
  return {
    sessionActive: data.transaction_active,
    energy: data.transaction_active
      ? numeric(data.session_energy_kwh)
      : entityNumber(hass.states[data.entities?.last_session_energy]),
    duration: data.transaction_active
      ? elapsed(data.session_started_at, now)
      : storedSessionDuration(hass.states[data.entities?.last_session_duration]),
    cost: entityNumber(lastCost),
    currency: lastCost?.attributes.unit_of_measurement || '',
  };
}
export type SessionSort = 'start' | 'end' | 'energy' | 'green' | 'cost' | 'identifier';
export function sessionRows(
  data: SessionHistoryData,
  query: string,
  sort: SessionSort,
  ascending: boolean,
) {
  const needle = query.trim().toLocaleLowerCase();
  const filtered = data.items.filter(
    (row) =>
      !needle ||
      [row.start_time, row.end_time, row.session_id, row.authorized_identifier].some((value) =>
        value?.toLocaleLowerCase().includes(needle),
      ),
  );
  const value = (row: SessionItem): string | number =>
    ({
      start: row.start_time || '',
      end: row.end_time || '',
      energy: row.energy_kwh ?? -1,
      green: sessionRowMetrics(row).green ?? -1,
      cost: sessionRowMetrics(row).cost ?? -1,
      identifier: row.authorized_identifier || '',
    })[sort];
  return filtered.sort((a, b) => {
    if (!!a.active !== !!b.active) return a.active ? -1 : 1;
    return (
      (typeof value(a) === 'number'
        ? Number(value(a)) - Number(value(b))
        : String(value(a)).localeCompare(String(value(b)))) * (ascending ? 1 : -1)
    );
  });
}

export function sessionPage<T>(items: T[], requestedPage: number, pageSize: number) {
  const size = Math.max(1, Math.floor(pageSize));
  const count = Math.max(1, Math.ceil(items.length / size));
  const index = Math.min(Math.max(0, Math.floor(requestedPage)), count - 1);
  const offset = index * size;
  return {
    items: items.slice(offset, offset + size),
    index,
    count,
    from: items.length ? offset + 1 : 0,
    to: Math.min(offset + size, items.length),
    total: items.length,
  };
}

export function selectedSession(items: SessionItem[], sessionId?: string) {
  return (
    items.find((item) => item.session_id === sessionId) ||
    items.find((item) => item.active) ||
    items[0]
  );
}
