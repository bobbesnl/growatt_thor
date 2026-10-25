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
