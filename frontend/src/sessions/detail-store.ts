import type { SessionDetailResponse, SessionItem } from '../shared/types';

export type SessionDetailLoader = (
  entryId: string,
  sessionId: string,
) => Promise<SessionDetailResponse>;
type DetailState =
  | { status: 'loading'; pending?: Promise<void> }
  | { status: 'loaded'; item: SessionItem }
  | { status: 'error' };

/** Own lazy session details, request deduplication and the current HA entry scope. */
export class SessionDetailStore {
  private entryId?: string;
  private readonly records = new Map<string, DetailState>();

  constructor(
    private readonly changed: () => void,
    private readonly capacity = 50,
  ) {
    if (!Number.isInteger(capacity) || capacity < 1)
      throw new Error('Session detail capacity must be a positive integer');
  }

  /** Called as part of the host's update; replies from the old scope become inert. */
  setEntry(entryId: string | undefined): boolean {
    if (this.entryId === entryId) return false;
    this.entryId = entryId;
    this.records.clear();
    return true;
  }

  clear(): void {
    this.records.clear();
  }

  retry(sessionId: string | null): void {
    if (sessionId && this.records.get(sessionId)?.status === 'error')
      this.records.delete(sessionId);
  }

  status(sessionId: string | null | undefined): DetailState['status'] | 'idle' {
    return (sessionId && this.records.get(sessionId)?.status) || 'idle';
  }

  resolve(summary: SessionItem | undefined): SessionItem | undefined {
    if (!summary?.session_id || summary.active || summary.power_curve !== undefined) return summary;
    const record = this.records.get(summary.session_id);
    if (record?.status !== 'loaded') return summary;
    // Keep the visible session when the bounded cache evicts its oldest entry.
    this.records.delete(summary.session_id);
    this.records.set(summary.session_id, record);
    return { ...summary, ...record.item };
  }

  async load(summary: SessionItem | undefined, loader?: SessionDetailLoader): Promise<void> {
    const sessionId = summary?.session_id;
    if (
      !sessionId ||
      summary.active ||
      summary.power_curve !== undefined ||
      !summary.detail_available
    )
      return;
    // Lit calls load after many unrelated HA updates. Reuse pending work and
    // retain errors until explicit retry, otherwise every update would retry I/O.
    const existing = this.records.get(sessionId);
    if (existing) return existing.status === 'loading' ? existing.pending : undefined;

    const record: Extract<DetailState, { status: 'loading' }> = { status: 'loading' };
    this.records.set(sessionId, record);
    while (this.records.size > this.capacity) {
      const oldest = this.records.keys().next().value;
      if (oldest !== undefined) this.records.delete(oldest);
    }
    this.changed();
    record.pending = this.fetch(sessionId, record, loader);
    return record.pending;
  }

  private async fetch(
    sessionId: string,
    pending: DetailState,
    loader?: SessionDetailLoader,
  ): Promise<void> {
    let result: DetailState;
    try {
      if (!this.entryId || !loader) throw new Error('Session detail service unavailable');
      const response = await loader(this.entryId, sessionId);
      if (response?.schema !== 1 || response.item?.session_id !== sessionId)
        throw new Error('Invalid session detail response');
      result = { status: 'loaded', item: response.item };
    } catch {
      result = { status: 'error' };
    }
    // Compare the request object, not just sessionId: another entry can have
    // the same ID and start a newer request while this reply is still in flight.
    // Entry changes, eviction and disconnects invalidate outstanding requests.
    if (this.records.get(sessionId) !== pending) return;
    this.records.set(sessionId, result);
    this.changed();
  }
}
