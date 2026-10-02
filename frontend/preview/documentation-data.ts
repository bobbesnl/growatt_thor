import type { SessionHistoryData, SessionItem } from '../src/shared/types';

/** Illustrative THOR-like sessions, not an export of a user's charger history. */
export function documentationHistory(): SessionHistoryData {
  // RFID identifiers are fictitious. Keep one Plug & Charge session for comparison.
  const examples: [string, string, number, number, number, string][] = [
    ['2026-10-02T13:01:05+02:00', '2026-10-02T17:32:16+02:00', 28.233, 0.65, 0.2, '04A1B2C3D4E580'],
    ['2026-09-30T17:05:11+02:00', '2026-09-30T19:46:02+02:00', 17.8, 0.25, 0.3, '0478ABCDEF1290'],
    ['2026-09-27T14:07:27+02:00', '2026-09-27T17:26:10+02:00', 22.1, 0.8, 0, 'freevenID'],
    ['2026-09-26T11:42:59+02:00', '2026-09-26T13:32:18+02:00', 11.7, 1, 0, '04A1B2C3D4E580'],
  ];
  const items: SessionItem[] = examples.map(
    ([start, end, energy, solarShare, batteryShare, identifier], index) => {
      const from = Date.parse(start),
        to = Date.parse(end);
      // Early current adjustments, a long steady plateau, then a vehicle pause.
      const shape: [number, number][] = [
        [0, 0],
        [0.002, 0.4],
        [0.005, 7.4],
        [0.052, 7.4],
        [0.055, 4.4],
        [0.09, 4.4],
        [0.095, 5.5],
        [0.12, 5.5],
        [0.125, 6.4],
        [0.14, 6.4],
        [0.145, 3.5],
        [0.225, 3.5],
        [0.23, 6.4],
        [0.29, 6.4],
        [0.3, 7.35],
        [0.4, 7.37],
        [0.5, 7.32],
        [0.6, 7.4],
        [0.7, 7.38],
        [0.8, 7.35],
        [0.885, 7.36],
        [0.887, 0],
        [1, 0],
      ];
      const nominal =
        (shape
          .slice(1)
          .reduce((sum, [x, y], i) => sum + ((x - shape[i][0]) * (y + shape[i][1])) / 2, 0) *
          (to - from)) /
        3600000;
      const power_curve: [string, number][] = shape.map(([x, y]) => [
        new Date(from + (to - from) * x).toISOString(),
        Math.round(((y * energy) / nominal) * 1000),
      ]);
      const at = (fraction: number) => new Date(from + (to - from) * fraction).toISOString();
      const solar = energy * solarShare,
        battery = energy * batteryShare;
      return {
        session_id: `documentation-${index}`,
        active: false,
        start_time: start,
        end_time: end,
        energy_kwh: energy,
        // Match backend accounting: complete allocation, direct solar only.
        green_energy_kwh: solar,
        cost: Math.round(energy * 0.3 * 100) / 100,
        duration_minutes: (to - from) / 60000,
        authorized_identifier: identifier,
        power_curve,
        source_energy_kwh: {
          direct_solar: solar,
          battery_unknown: battery,
          direct_grid: energy - solar - battery,
          unknown: 0,
        },
        effective_grid_cost: (energy - solar - battery) * 0.3,
        accounting_coverage: 1,
        accounting_quality: 'derived',
        accounting_policy: { id: 'grid_first', version: 1 },
        events: [
          {
            type: 'plugged_in',
            at: new Date(from - 172000).toISOString(),
            source: 'ocpp',
            certainty: 'observed',
          },
          { type: 'transaction_started', at: start, source: 'ocpp', certainty: 'observed' },
          { type: 'energy_flow_started', at: at(0.002), source: 'meter', certainty: 'derived' },
          {
            type: 'charging_paused',
            at: at(0.887),
            source: 'ocpp',
            certainty: 'observed',
            reason: 'suspended_ev',
          },
          {
            type: 'transaction_stopped',
            at: end,
            source: 'ocpp',
            certainty: 'observed',
            reason: 'Remote',
          },
        ],
      };
    },
  );
  return {
    schema: 1,
    total_count: items.length,
    total_energy_kwh: items.reduce((sum, item) => sum + item.energy_kwh!, 0),
    total_green_energy_kwh: items.reduce((sum, item) => sum + (item.green_energy_kwh ?? 0), 0),
    total_cost: items.reduce((sum, item) => sum + item.cost!, 0),
    items,
  };
}
