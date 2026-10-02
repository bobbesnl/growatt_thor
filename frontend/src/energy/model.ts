import { clamp } from '../shared/model';
import type { CardData } from '../shared/types';

export type GridDirection = 'import' | 'export' | 'balanced' | 'unavailable';
export type FlowTone = 'import' | 'export' | 'balanced' | 'unavailable';
export type ChargingSource = 'solar' | 'battery' | 'grid' | 'unknown';

export interface GaugeTarget {
  fraction: number;
  kw: number;
  label: 'zeroGridPoint' | 'pvControlPoint';
  hint: 'zeroGridPointHint' | 'pvControlPointHint';
}

export interface GaugeOverflow {
  startFraction: number;
  fraction: number;
  excessKw: number;
  severity: 'warning' | 'critical';
}

export interface GaugeSourceSegment {
  source: ChargingSource;
  label: 'sourceSolar' | 'sourceBattery' | 'sourceGrid' | 'sourceUnknown';
  startFraction: number;
  fraction: number;
  kw: number;
}

export interface PowerFlowView {
  visible: boolean;
  available: boolean;
  direction: GridDirection;
  tone: FlowTone;
  icon: string;
  valueKw: number | null;
  label: 'gridImport' | 'gridExport' | 'gridBalanced' | 'gridPowerUnavailable';
  target: GaugeTarget | null;
  overflow: GaugeOverflow | null;
  sources: GaugeSourceSegment[];
  gridImportLimitKw: number | null;
}

const GRID_BALANCE_DEADBAND_W = 50;
const SOURCE_LABELS = {
  solar: 'sourceSolar',
  battery: 'sourceBattery',
  grid: 'sourceGrid',
  unknown: 'sourceUnknown',
} as const;

function signedNumeric(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function gridDirection(gridW: number | null): GridDirection {
  if (gridW === null) return 'unavailable';
  if (gridW > GRID_BALANCE_DEADBAND_W) return 'import';
  if (gridW < -GRID_BALANCE_DEADBAND_W) return 'export';
  return 'balanced';
}

function sourceSegments(
  data: CardData,
  measuredPowerKw: number | null,
  maximumKw: number | null,
  usable: boolean,
): GaugeSourceSegment[] {
  const sourceData = data.power_flow?.charging_sources;
  if (!sourceData || !usable || measuredPowerKw === null || !maximumKw || measuredPowerKw <= 0)
    return [];

  const sourceOrder: ChargingSource[] = ['solar', 'battery', 'grid', 'unknown'];
  const rawWatts = {
    solar: signedNumeric(sourceData.solar_w),
    battery: signedNumeric(sourceData.battery_w),
    grid: signedNumeric(sourceData.grid_w),
    unknown: signedNumeric(sourceData.unknown_w),
  };
  if (!sourceOrder.some((source) => rawWatts[source] !== null)) return [];

  const visibleTotalW = Math.min(measuredPowerKw, maximumKw) * 1000;
  const positiveWatts = Object.fromEntries(
    sourceOrder.map((source) => [source, Math.max(0, rawWatts[source] ?? 0)]),
  ) as Record<ChargingSource, number>;
  const reportedTotalW = sourceOrder.reduce((sum, source) => sum + positiveWatts[source], 0);
  const scale = reportedTotalW > visibleTotalW ? visibleTotalW / reportedTotalW : 1;
  for (const source of sourceOrder) positiveWatts[source] *= scale;
  positiveWatts.unknown += Math.max(
    0,
    visibleTotalW - sourceOrder.reduce((sum, source) => sum + positiveWatts[source], 0),
  );

  let startFraction = 0;
  return sourceOrder.flatMap((source) => {
    const watts = positiveWatts[source];
    if (watts < 1) return [];
    const fraction = (watts / (maximumKw * 1000)) * 100;
    const segment = {
      source,
      label: SOURCE_LABELS[source],
      startFraction,
      fraction,
      kw: watts / 1000,
    };
    startFraction += fraction;
    return [segment];
  });
}

/**
 * Derive the compact grid balance and the charger controller's dynamic gauge target.
 *
 * The marker is a net-grid operating point, not a claim about the physical source of
 * each electron. This remains correct when battery telemetry is added later: direct
 * PV/grid/battery contributions can be rendered as gauge segments without replacing
 * the balance or target model.
 */
export function powerFlowView(
  data: CardData,
  chargerPowerKw: number | null,
  maximumKw: number | null,
  connected: boolean,
  now: number,
): PowerFlowView {
  const pvMode = data.working_mode?.startsWith('pv_linkage') === true;
  const snapshot = data.power_flow;
  const gridW = snapshot?.grid_sign === 'positive_import' ? signedNumeric(snapshot.grid_w) : null;
  const receivedAt = Date.parse(snapshot?.received_at || '');
  const staleAfterMs = Math.max(15, snapshot?.stale_after_s || 95) * 1000;
  const fresh =
    Number.isFinite(receivedAt) && receivedAt <= now + 60_000 && now - receivedAt <= staleAfterMs;
  const available =
    connected && data.external_meter_health === 'healthy' && gridW !== null && fresh;
  const direction = available ? gridDirection(gridW) : 'unavailable';
  const visible = connected && (available || pvMode);
  const label = {
    import: 'gridImport',
    export: 'gridExport',
    balanced: 'gridBalanced',
    unavailable: 'gridPowerUnavailable',
  }[direction] as PowerFlowView['label'];
  const icon = {
    import: 'mdi:transmission-tower-import',
    export: 'mdi:transmission-tower-export',
    balanced: 'mdi:scale-balance',
    unavailable: 'mdi:transmission-tower-off',
  }[direction];

  const measuredPowerKw = chargerPowerKw ?? (!data.transaction_active && available ? 0 : null);
  const sources = sourceSegments(data, measuredPowerKw, maximumKw, available);
  const configuredAllowance = signedNumeric(snapshot?.grid_import_limit_kw);
  const gridImportLimitKw =
    data.working_mode === 'pv_linkage' && configuredAllowance !== null
      ? Math.max(0, configuredAllowance)
      : null;

  let target: GaugeTarget | null = null;
  let overflow: GaugeOverflow | null = null;
  if (pvMode && available && measuredPowerKw !== null && maximumKw) {
    // At otherwise unchanged site load/generation, subtracting current grid import
    // (or adding current export) yields the charging power at zero grid exchange.
    const zeroGridKw = Math.max(0, measuredPowerKw - gridW! / 1000);
    const targetKw = Math.min(maximumKw, zeroGridKw + (gridImportLimitKw ?? 0));
    const fraction = clamp((targetKw / maximumKw) * 100);
    target = {
      fraction,
      kw: targetKw,
      label: gridImportLimitKw === null ? 'zeroGridPoint' : 'pvControlPoint',
      hint: gridImportLimitKw === null ? 'zeroGridPointHint' : 'pvControlPointHint',
    };

    // Only paint the measured portion beyond the controller target. The same
    // difference is the grid import above the mode's configured allowance while
    // the current site load remains unchanged. Ignore the meter deadband so the
    // gauge does not flicker around its operating point.
    const allowedImportKw = gridImportLimitKw ?? 0;
    const excessKw = Math.max(0, gridW! / 1000 - allowedImportKw);
    const measuredFraction = clamp((measuredPowerKw / maximumKw) * 100);
    const overflowFraction = Math.max(0, measuredFraction - fraction);
    if (excessKw > GRID_BALANCE_DEADBAND_W / 1000 && overflowFraction > 0) {
      overflow = {
        startFraction: fraction,
        fraction: overflowFraction,
        excessKw,
        severity: excessKw >= Math.max(0.5, maximumKw * 0.1) ? 'critical' : 'warning',
      };
    }
  }

  return {
    visible,
    available,
    direction,
    tone: direction,
    icon,
    valueKw: available ? Math.abs(gridW!) / 1000 : null,
    label,
    target,
    overflow,
    sources,
    gridImportLimitKw,
  };
}
