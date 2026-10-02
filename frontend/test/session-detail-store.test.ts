import assert from 'node:assert/strict';
import test from 'node:test';
import { SessionDetailStore, type SessionDetailLoader } from '../src/sessions/detail-store';
import type { SessionDetailResponse, SessionItem } from '../src/shared/types';

const summary = (session_id = 'one'): SessionItem => ({
  session_id,
  start_time: null,
  end_time: null,
  energy_kwh: 2,
  green_energy_kwh: null,
  cost: null,
  duration_minutes: null,
  authorized_identifier: null,
  detail_available: true,
});
const response = (session_id = 'one'): SessionDetailResponse => ({
  schema: 1,
  item: { ...summary(session_id), power_curve: [['2026-09-30T12:00:00Z', 1000]] },
});
function deferred() {
  let resolve!: (value: SessionDetailResponse) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<SessionDetailResponse>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

test('details share one pending request and merge only completed session summaries', async () => {
  const notifications: string[] = [];
  const store = new SessionDetailStore(() => notifications.push(store.status('one')));
  store.setEntry('entry-a');
  const pending = deferred();
  const calls: string[][] = [];
  const loader: SessionDetailLoader = (entry, session) => {
    calls.push([entry, session]);
    return pending.promise;
  };
  const first = store.load(summary(), loader);
  const second = store.load(summary(), loader);
  assert.equal(store.status('one'), 'loading');
  assert.equal(store.resolve(summary())?.power_curve, undefined);
  pending.resolve(response());
  await Promise.all([first, second]);
  await store.load(summary(), loader);
  assert.deepEqual(calls, [['entry-a', 'one']]);
  assert.deepEqual(notifications, ['loading', 'loaded']);
  assert.deepEqual(store.resolve(summary())?.power_curve, response().item.power_curve);
  const active = { ...summary(), active: true };
  assert.equal(store.resolve(active), active);
  const inline = { ...summary(), power_curve: [] };
  assert.equal(store.resolve(inline), inline);
});

test('switching entries rejects stale replies even when session identities coincide', async () => {
  let notifications = 0;
  const store = new SessionDetailStore(() => notifications++);
  store.setEntry('entry-a');
  const old = deferred();
  const first = store.load(summary(), () => old.promise);
  store.setEntry('entry-b');
  const current = deferred();
  const second = store.load(summary(), () => current.promise);
  old.resolve(response());
  await first;
  assert.equal(store.status('one'), 'loading');
  assert.equal(store.resolve(summary())?.power_curve, undefined);
  assert.equal(notifications, 2);
  current.resolve({ ...response(), item: { ...response().item, energy_kwh: 7 } });
  await second;
  assert.equal(store.resolve(summary())?.energy_kwh, 7);
});

test('failed loads wait for explicit retry and validate schema and requested identity', async () => {
  const store = new SessionDetailStore(() => {});
  store.setEntry('entry-a');
  let calls = 0;
  const failing = async () => {
    calls++;
    throw new Error('offline');
  };
  await store.load(summary(), failing);
  await store.load(summary(), failing);
  assert.equal(calls, 1);
  assert.equal(store.status('one'), 'error');
  for (const invalid of [{ ...response(), schema: 2 }, response('wrong')]) {
    store.retry('one');
    await store.load(summary(), async () => invalid);
    assert.equal(store.status('one'), 'error');
    assert.equal(store.resolve(summary())?.power_curve, undefined);
  }
  store.retry('one');
  await store.load(summary(), async () => response());
  assert.equal(store.status('one'), 'loaded');
});

test('active, inline and unavailable details never request historical data', async () => {
  const store = new SessionDetailStore(() => {});
  store.setEntry('entry-a');
  let calls = 0;
  const loader = async () => {
    calls++;
    return response();
  };
  for (const item of [
    undefined,
    { ...summary(), session_id: null },
    { ...summary(), active: true },
    { ...summary(), power_curve: [] },
    { ...summary(), detail_available: false },
  ])
    await store.load(item, loader);
  assert.equal(calls, 0);
  await store.load(summary());
  assert.equal(store.status('one'), 'error');
});

test('bounded detail storage retains the visible session and ignores cleared pending replies', async () => {
  const store = new SessionDetailStore(() => {}, 2);
  store.setEntry('entry-a');
  const loader: SessionDetailLoader = async (_entry, id) => response(id);
  await store.load(summary('one'), loader);
  await store.load(summary('two'), loader);
  store.resolve(summary('one'));
  await store.load(summary('three'), loader);
  assert.equal(store.status('one'), 'loaded');
  assert.equal(store.status('two'), 'idle');
  const pending = deferred();
  const load = store.load(summary('four'), () => pending.promise);
  store.clear();
  pending.resolve(response('four'));
  await load;
  assert.equal(store.status('four'), 'idle');
});
