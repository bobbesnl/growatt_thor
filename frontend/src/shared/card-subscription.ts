import type { CardData, Hass } from './types';

export const CARD_SUBSCRIBE = 'growatt_thor/card/subscribe';
/** Wait before trying again after a refused subscription (older integration, unloaded entry). */
export const RESUBSCRIBE_DELAY_MS = 30_000;

type CardMessage = { type: 'data'; data: CardData } | { type: 'unloaded' };

/**
 * Card data pushed by the integration, with the `thor_card` attribute as fallback.
 *
 * The subscription carries the same payload as the attribute. Until it delivers
 * data, after it fails, or when it belongs to another entry, `resolve` returns
 * the attribute, so an integration without the subscription keeps working.
 */
export class CardDataSubscription {
  private data?: CardData;
  private entryId?: string;
  private unsubscribe?: Promise<(() => unknown) | undefined>;
  private retryAt = 0;

  constructor(
    private readonly changed: () => void,
    private readonly now: () => number = Date.now,
  ) {}

  /** Subscribe for `entryId`, or keep the running subscription; call on every hass update. */
  update(hass: Hass | undefined, entryId: string | undefined) {
    const connection = hass?.connection;
    if (!connection?.subscribeMessage || !entryId) return;
    if (entryId === this.entryId && this.unsubscribe) return;
    if (entryId === this.entryId && this.now() < this.retryAt) return;
    this.close();
    this.entryId = entryId;
    this.unsubscribe = connection
      .subscribeMessage<CardMessage>((message) => this.receive(entryId, message), {
        type: CARD_SUBSCRIBE,
        entry_id: entryId,
      })
      .catch(() => {
        this.stop(entryId);
        return undefined;
      });
  }

  /** Prefer pushed data for the same entry; otherwise use the attribute. */
  resolve(attribute: CardData | undefined): CardData | undefined {
    if (!this.data || !attribute || this.data.entry_id !== attribute.entry_id) return attribute;
    return this.data;
  }

  close() {
    const unsubscribe = this.unsubscribe;
    this.unsubscribe = undefined;
    this.data = undefined;
    void unsubscribe?.then((stop) => stop?.()).catch(() => undefined);
  }

  private receive(entryId: string, message: CardMessage) {
    if (entryId !== this.entryId) return;
    if (message.type === 'data') this.data = message.data;
    else this.stop(entryId);
    this.changed();
  }

  /** The integration ended or refused the subscription; fall back and retry later. */
  private stop(entryId: string) {
    if (entryId !== this.entryId) return;
    const unsubscribe = this.unsubscribe;
    this.unsubscribe = undefined;
    this.data = undefined;
    this.retryAt = this.now() + RESUBSCRIBE_DELAY_MS;
    // Drop the client-side handler; the server side has already ended.
    void unsubscribe?.then((stop) => stop?.()).catch(() => undefined);
  }
}
