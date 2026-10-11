/**
 * Helpers shared by the in-app chat and retention:
 *  - serial(): serialises writes per project (message sequence numbers, participant creation);
 *  - toWallClock(): the system stores message times as wall-clock-as-UTC in the project's timezone;
 *  - scheduleReanalysis(): debounced incremental analysis, so a burst of messages causes ONE analysis job.
 */
import { prisma } from '../db';
import { config } from '../config';
import { JobQueue } from '../queues';

const chain = new Map<string, Promise<unknown>>();
export const serial = <T,>(key: string, fn: () => Promise<T>): Promise<T> => {
  const next = (chain.get(key) ?? Promise.resolve()).then(fn, fn);
  chain.set(key, next.catch(() => undefined));
  return next;
};

export function toWallClock(ts: Date, timeZone: string): Date {
  const parts = new Intl.DateTimeFormat('en-GB', { timeZone, hour12: false, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
    .formatToParts(ts).reduce<Record<string, string>>((a, p) => { a[p.type] = p.value; return a; }, {});
  const hour = parts.hour === '24' ? '00' : parts.hour;
  return new Date(`${parts.year}-${parts.month}-${parts.day}T${hour}:${parts.minute}:${parts.second}.000Z`);
}

const timers = new Map<string, { timer: NodeJS.Timeout; first: number }>();
const MAX_WAIT_MS = 5 * 60_000;

export function scheduleReanalysis(projectId: string, queue: JobQueue, debounceMs = config().ANALYSIS_DEBOUNCE_MS): void {
  const prev = timers.get(projectId);
  const first = prev?.first ?? Date.now();
  if (prev) clearTimeout(prev.timer);
  const wait = Math.max(0, Math.min(debounceMs, MAX_WAIT_MS - (Date.now() - first)));       // a constant stream cannot postpone analysis forever
  timers.set(projectId, { first, timer: setTimeout(() => void fire(projectId, queue, debounceMs), wait) });
}

async function fire(projectId: string, queue: JobQueue, debounceMs: number): Promise<void> {
  timers.delete(projectId);
  try {
    const active = await prisma.analysisJob.findFirst({ where: { projectId, status: { in: ['QUEUED', 'RUNNING'] } } });
    if (active) { scheduleReanalysis(projectId, queue, Math.max(debounceMs, 5_000)); return; }   // never run two analyses of one project at once
    const job = await prisma.analysisJob.create({ data: { projectId, status: 'QUEUED', stage: 'Queued', progress: 5 } });
    await queue.enqueue(job.id);
  } catch (e) { console.error('[analysis] could not schedule', (e as Error).message); }
}

export const _timersForTests = timers;
