import assert from 'node:assert/strict';
import { test } from 'node:test';
import { SessionChartHost } from '../src/sessions/chart-host';

function fixture() {
  const charts: Array<{ element: HTMLDivElement; disposed: number; resized: number }> = [];
  const observers: Array<{ elements: Element[]; disconnected: number; resize: () => void }> = [];
  let draws = 0;
  const host = new SessionChartHost(
    (element) => {
      const state = { element, disposed: 0, resized: 0 };
      charts.push(state);
      return {
        getDom: () => state.element,
        dispose: () => state.disposed++,
        resize: () => state.resized++,
      };
    },
    () => draws++,
    (resize) => {
      const state = { elements: [] as Element[], disconnected: 0, resize };
      observers.push(state);
      return {
        observe: (element) => state.elements.push(element),
        disconnect: () => state.disconnected++,
      };
    },
  );
  return { host, charts, observers, draws: () => draws };
}

const element = () => ({}) as HTMLDivElement;

test('ready -> notice -> ready binds a fresh chart and resize observer', () => {
  const f = fixture();
  const first = element();
  assert.equal(f.host.attach(first), true);
  assert.equal(f.host.attach(first), false);
  f.host.disconnect();
  const second = element();
  assert.equal(f.host.attach(second), true);
  assert.equal(f.charts[0].disposed, 1);
  assert.equal(f.observers[0].disconnected, 1);
  assert.deepEqual(f.observers[1].elements, [second]);
  f.observers[1].resize();
  assert.equal(f.charts[0].resized, 0);
  assert.equal(f.charts[1].resized, 1);
  assert.equal(f.draws(), 1);
});

test('replacing the DOM element disposes an existing chart before attaching', () => {
  const f = fixture();
  f.host.attach(element());
  const replacement = element();
  assert.equal(f.host.attach(replacement), true);
  assert.equal(f.host.chart?.getDom(), replacement);
  assert.equal(f.charts[0].disposed, 1);
  assert.equal(f.observers[0].disconnected, 1);
});

test('a chart appearing after an initial notice and reconnect is observed', () => {
  const f = fixture();
  assert.equal(f.host.attach(undefined), false);
  const target = element();
  assert.equal(f.host.attach(target), true);
  f.host.disconnect();
  f.host.disconnect();
  assert.equal(f.charts[0].disposed, 1);
  assert.equal(f.host.attach(target), true);
  f.observers[1].resize();
  assert.equal(f.charts[1].resized, 1);
});
