import { EventEmitter } from 'node:events';
import IORedis from 'ioredis';
import { config } from '../config';

/**
 * Live events (job progress, completion, new notifications) for the dashboard.
 * Payloads carry ids, stage names and numbers only: no message text, no client data. Authorization happens when an event is DELIVERED
 * (see controllers/events.ts), so a published event can never reach a user who cannot see its project.
 *
 * Single process: an in-memory emitter. With REDIS_URL set the same events travel over a Redis channel, so a worker process (which runs the
 * analysis) reaches the API process that holds the browser connections. Delivery is at-most-once and best effort: the dashboard still
 * works by polling if the stream drops (the frontend falls back to refetching).
 */
export interface LiveEvent {
  type: 'analysis.progress' | 'analysis.completed' | 'analysis.failed' | 'notification.created' | 'chat.message' | 'chat.room' | 'chat.typing';
  projectId: string;                  // '' for a direct-message room
  roomId?: string;                    // chat events carry ids only; the client fetches the text
  userIds?: string[];                 // when set, ONLY these users receive the event (room members); no project check applies
  actorId?: string;                   // chat.typing: who is typing (the client shows the member's name)
  jobId?: string;
  progress?: number;
  stage?: string;
  at: string;
}

const CHANNEL = 'wa:events';

class Bus {
  private local = new EventEmitter();
  private pub?: IORedis;
  private sub?: IORedis;

  constructor() { this.local.setMaxListeners(1000); }

  private ensureRedis() {
    const url = config().REDIS_URL;
    if (!url || this.pub) return Boolean(this.pub);
    this.pub = new IORedis(url, { maxRetriesPerRequest: 1, lazyConnect: false });
    this.sub = new IORedis(url, { maxRetriesPerRequest: null });
    this.pub.on('error', () => undefined);
    this.sub.on('error', () => undefined);
    void this.sub.subscribe(CHANNEL);
    this.sub.on('message', (_c, msg) => { try { this.local.emit('event', JSON.parse(msg)); } catch { /* ignore malformed */ } });
    return true;
  }

  publish(e: Omit<LiveEvent, 'at'>): void {
    const ev: LiveEvent = { ...e, at: new Date().toISOString() };
    if (this.ensureRedis()) {
      this.pub!.publish(CHANNEL, JSON.stringify(ev)).catch(() => this.local.emit('event', ev));   // Redis down: still reach this process
    } else {
      this.local.emit('event', ev);
    }
  }

  subscribe(fn: (e: LiveEvent) => void): () => void {
    this.ensureRedis();
    this.local.on('event', fn);
    return () => this.local.off('event', fn);
  }

  async close() { await Promise.all([this.pub?.quit().catch(() => undefined), this.sub?.quit().catch(() => undefined)]); this.pub = this.sub = undefined; }
}

export const events = new Bus();
