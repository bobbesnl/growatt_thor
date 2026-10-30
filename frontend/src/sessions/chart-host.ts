/** Own the chart and observer for the current Lit-rendered chart element. */
interface HostedChart {
  getDom(): HTMLElement | undefined;
  dispose(): void;
  resize(): void;
}
interface SizeObserver {
  observe(element: Element): void;
  disconnect(): void;
}

export class SessionChartHost<Chart extends HostedChart> {
  chart?: Chart;
  private observer?: SizeObserver;

  constructor(
    private readonly create: (element: HTMLDivElement) => Chart,
    private readonly onResize: () => void,
    private readonly observe: (callback: () => void) => SizeObserver = (callback) =>
      new ResizeObserver(callback),
  ) {}

  /** Return whether event handlers need to be installed on a new instance. */
  attach(element?: HTMLDivElement): boolean {
    if (this.chart && this.chart.getDom() !== element) this.disconnect();
    if (!element || this.chart) return false;
    this.chart = this.create(element);
    this.observer = this.observe(() => {
      this.chart?.resize();
      this.onResize();
    });
    this.observer.observe(element);
    return true;
  }

  disconnect(): void {
    this.observer?.disconnect();
    this.observer = undefined;
    this.chart?.dispose();
    this.chart = undefined;
  }
}

interface ChartEvents {
  on(name: string, callback: (event: unknown) => void): unknown;
}
interface ChartEventHandlers {
  legend(selected: Record<string, boolean>): void;
  zoom(range: { start: number; end: number }): void;
  axisBreak(key: string, expanded: boolean): void;
}
function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}

/** Narrow ECharts' untyped events once, at the adapter boundary. */
export function bindSessionChartEvents(chart: ChartEvents, handlers: ChartEventHandlers) {
  chart.on('legendselectchanged', (event) => {
    const selected = record(record(event).selected);
    handlers.legend(
      Object.fromEntries(
        Object.entries(selected).filter(([, value]) => typeof value === 'boolean'),
      ) as Record<string, boolean>,
    );
  });
  chart.on('datazoom', (event) => {
    const data = record(event);
    const range = record(Array.isArray(data.batch) ? data.batch[0] : event);
    if (
      typeof range.start === 'number' &&
      Number.isFinite(range.start) &&
      typeof range.end === 'number' &&
      Number.isFinite(range.end)
    )
      handlers.zoom({ start: range.start, end: range.end });
  });
  chart.on('axisbreakchanged', (event) => {
    const breaks = record(event).breaks;
    if (!Array.isArray(breaks)) return;
    for (const item of breaks) {
      const axisBreak = record(item);
      handlers.axisBreak(`${axisBreak.start}:${axisBreak.end}`, !!axisBreak.isExpanded);
    }
  });
}
