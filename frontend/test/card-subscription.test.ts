import assert from 'node:assert/strict';
import test from 'node:test';
import {
  CARD_SUBSCRIBE,
  CardDataSubscription,
  RESUBSCRIBE_DELAY_MS,
} from '../src/shared/card-subscription';
import type { CardData, Hass } from '../src/shared/types';
import { hass, makeData } from './fixtures';

type Listener = (message: unknown) => void;

function fakeConnection(refuse = false) {
  const subscriptions: { message: Record<string, unknown>; listener: Listener }[] = [];
  let stopped = 0;
  const connection = {
    subscribeMessage<T>(listener: (message: T) => void, message: Record<string, unknown>) {
      subscriptions.push({ message, listener: listener as Listener });
      return refuse
        ? Promise.reject(new Error('unknown_command'))
        : Promise.resolve(() => {
            stopped++;
          });
    },
  };
  return { connection, subscriptions, stopped: () => stopped };
}

const flush = () => new Promise((resolve) => setImmediate(resolve));
const attribute = makeData({ power_w: 1000 });
const pushed: CardData = makeData({ power_w: 7200 });

test('without a WebSocket connection the card keeps using the attribute', () => {
  const subscription = new CardDataSubscription(() => {});
  subscription.update(hass, 'one');
  assert.equal(subscription.resolve(attribute), attribute);
});

test('pushed data replaces the attribute only for the same entry', async () => {
  const fake = fakeConnection();
  let changes = 0;
  const subscription = new CardDataSubscription(() => changes++);
  const withConnection = { ...hass, connection: fake.connection } as Hass;

  subscription.update(withConnection, 'one');
  subscription.update(withConnection, 'one');
  await flush();
  assert.deepEqual(
    fake.subscriptions.map((item) => item.message),
    [{ type: CARD_SUBSCRIBE, entry_id: 'one' }],
  );
  assert.equal(subscription.resolve(attribute), attribute);

  fake.subscriptions[0].listener({ type: 'data', data: pushed });
  assert.equal(changes, 1);
  assert.equal(subscription.resolve(attribute), pushed);
  assert.equal(subscription.resolve(makeData({ entry_id: 'two' }))?.entry_id, 'two');
  assert.equal(subscription.resolve(undefined), undefined);

  // Another entry ends the old subscription before the new one starts.
  subscription.update(withConnection, 'two');
  await flush();
  assert.equal(fake.stopped(), 1);
  assert.equal(fake.subscriptions.at(-1)?.message.entry_id, 'two');
  fake.subscriptions[0].listener({ type: 'data', data: pushed });
  assert.equal(subscription.resolve(attribute), attribute);
});

test('an unloaded entry falls back to the attribute and subscribes again later', async () => {
  const fake = fakeConnection();
  let now = 1000;
  const subscription = new CardDataSubscription(
    () => {},
    () => now,
  );
  const withConnection = { ...hass, connection: fake.connection } as Hass;
  subscription.update(withConnection, 'one');
  await flush();
  fake.subscriptions[0].listener({ type: 'data', data: pushed });
  fake.subscriptions[0].listener({ type: 'unloaded' });
  await flush();

  assert.equal(subscription.resolve(attribute), attribute);
  assert.equal(fake.stopped(), 1);
  subscription.update(withConnection, 'one');
  assert.equal(fake.subscriptions.length, 1);
  now += RESUBSCRIBE_DELAY_MS;
  subscription.update(withConnection, 'one');
  assert.equal(fake.subscriptions.length, 2);
});

test('a refused subscription keeps the attribute and retries after the delay', async () => {
  const fake = fakeConnection(true);
  let now = 0;
  const subscription = new CardDataSubscription(
    () => {},
    () => now,
  );
  const withConnection = { ...hass, connection: fake.connection } as Hass;
  subscription.update(withConnection, 'one');
  await flush();
  subscription.update(withConnection, 'one');
  assert.equal(fake.subscriptions.length, 1);
  assert.equal(subscription.resolve(attribute), attribute);
  now = RESUBSCRIBE_DELAY_MS;
  subscription.update(withConnection, 'one');
  assert.equal(fake.subscriptions.length, 2);
});

test('closing the card ends the subscription and forgets pushed data', async () => {
  const fake = fakeConnection();
  const subscription = new CardDataSubscription(() => {});
  const withConnection = { ...hass, connection: fake.connection } as Hass;
  subscription.update(withConnection, 'one');
  await flush();
  fake.subscriptions[0].listener({ type: 'data', data: pushed });

  subscription.close();
  await flush();
  assert.equal(fake.stopped(), 1);
  assert.equal(subscription.resolve(attribute), attribute);
  // A reconnected card subscribes again without waiting.
  subscription.update(withConnection, 'one');
  assert.equal(fake.subscriptions.length, 2);
});
