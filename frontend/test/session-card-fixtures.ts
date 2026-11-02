import type { SessionItem, SessionHistoryData } from '../src/shared/types';
import { sessionTranslate } from '../src/sessions/locales';

export function sessionFixture(extra: Partial<SessionItem> = {}): SessionItem {
  return {
    session_id: 'session-42',
    start_time: '2026-10-30T22:50:00Z',
    end_time: '2026-10-30T23:10:00Z',
    energy_kwh: 1.2,
    green_energy_kwh: 0.7,
    cost: 0.3,
    duration_minutes: 20,
    authorized_identifier: 'CARD-42',
    authorized_alias: 'Family car',
    power_curve: [
      ['2026-10-30T22:50:00Z', 7000],
      ['2026-10-30T23:10:00Z', 0],
    ],
    measured_current_sum_curve_a: [
      ['2026-10-30T22:50:00Z', 30],
      ['2026-10-30T22:51:00Z', null],
    ],
    configured_current_limit_curve_a: [['2026-10-30T22:50:00Z', 16]],
    site_pv_surplus_curve_w: [['2026-10-30T22:50:00Z', 8000]],
    site_house_load_curve_w: [['2026-10-30T22:50:00Z', 1000]],
    site_house_load_source: 'site_balance',
    site_battery_curve_w: [
      ['2026-10-30T22:50:00Z', -2000],
      ['2026-10-30T22:52:00Z', null],
    ],
    events: [
      {
        type: 'transaction_started',
        at: '2026-10-30T22:50:00Z',
        source: 'ocpp',
        certainty: 'observed',
      },
      {
        type: 'charging_paused',
        at: '2026-10-30T23:00:00Z',
        source: 'ocpp',
        certainty: 'provisional',
        reason: 'suspended_ev',
      },
    ],
    ...extra,
  };
}

export function sessionHistory(items: SessionItem[]): SessionHistoryData {
  return {
    schema: 1,
    items,
    total_energy_kwh: 10,
    total_green_energy_kwh: 7,
    total_cost: 3,
    total_count: 4,
  };
}

interface ChartCase {
  name: string;
  session?: SessionItem;
  width: number;
  dark: boolean;
  language: string;
  timeZone: string;
  reducedMotion: boolean;
  legendSelected: Record<string, boolean>;
  expandedBreaks: Set<string>;
}

export function sessionChartCases(): ChartCase[] {
  const cases: ChartCase[] = [];
  const add = (name: string, extra: Partial<ChartCase> = {}) =>
    cases.push({
      name,
      session: sessionFixture(),
      width: 900,
      dark: false,
      language: 'en',
      timeZone: 'Europe/Berlin',
      reducedMotion: false,
      legendSelected: {},
      expandedBreaks: new Set(),
      ...extra,
    });
  for (const width of [390, 600, 601, 1100])
    for (const dark of [false, true])
      for (const language of ['en', 'de'])
        add(`${width}-${dark}-${language}`, { width, dark, language });
  const t = sessionTranslate('en');
  const names = [
    t('seriesPower'),
    t('seriesPvSurplus'),
    `≈ ${t('seriesHouseLoad')}`,
    t('seriesBatteryFlow'),
    t('seriesMeasuredCurrentSum'),
    t('seriesConfiguredCurrentLimit'),
    t('seriesEvents'),
  ];
  for (let hidden = 1; hidden <= names.length; hidden++)
    add(`hidden-${hidden}`, {
      legendSelected: Object.fromEntries(names.slice(0, hidden).map((name) => [name, false])),
    });
  add('reduced-motion', { reducedMotion: true });
  add('utc-day', { timeZone: 'UTC' });
  add('no-session', { session: undefined });
  const noCurves: Partial<SessionItem> = {
    power_curve: [],
    measured_current_sum_curve_a: [],
    configured_current_limit_curve_a: [],
    site_pv_surplus_curve_w: [],
    site_house_load_curve_w: [],
    site_battery_curve_w: [],
  };
  add('events-only', { session: sessionFixture(noCurves) });
  add('current-only', {
    session: sessionFixture({
      ...noCurves,
      measured_current_sum_curve_a: [['2026-10-30T22:50:00Z', 30]],
    }),
  });
  add('battery-only', {
    session: sessionFixture({
      ...noCurves,
      site_battery_curve_w: [['2026-10-30T22:50:00Z', -2000]],
    }),
  });
  add('unknown-values', {
    session: sessionFixture({
      ...noCurves,
      site_pv_surplus_curve_w: [['2026-10-30T22:50:00Z', null]],
    }),
  });
  add('long-break', {
    session: sessionFixture({
      ...noCurves,
      power_curve: [
        ['2026-10-30T22:00:00Z', 7200],
        ['2026-11-01T02:00:00Z', 0],
      ],
      events: [],
    }),
    expandedBreaks: new Set([
      `${Date.parse('2026-10-30T22:10:00Z')}:${Date.parse('2026-11-01T01:50:00Z')}`,
    ]),
  });
  return cases;
}
