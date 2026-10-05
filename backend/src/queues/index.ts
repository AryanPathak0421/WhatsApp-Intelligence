import IORedis from 'ioredis';
import { Queue, Worker } from 'bullmq';
import { config } from '../config';
import { runAnalysisJob } from '../services/analysis';

export interface JobQueue {
  enqueue(jobId: string): Promise<void>;
  /** inline mode only: resolves when all queued jobs are done (used by tests) */
  idle(): Promise<void>;
  close(): Promise<void>;
  /** Queue depth by state, or null when the queue is the in-process fallback. */
  stats(): Promise<Record<string, number> | null>;
  ping(): Promise<boolean>;
}

/** No-Redis fallback: runs jobs sequentially in-process (dev / tests). Still asynchronous to the HTTP request. */
class InlineQueue implements JobQueue {
  private chain: Promise<unknown> = Promise.resolve();
  async enqueue(jobId: string) {
    this.chain = this.chain.then(() => runAnalysisJob(jobId)).catch((e) => console.error('[inline-queue]', e?.message));
  }
  idle() { return this.chain.then(() => undefined); }
  async close() { await this.idle(); }
  async stats() { return null; }
  async ping() { return true; }
}

export const QUEUE_NAME = 'wa-analysis';
const connection = () => new IORedis(config().REDIS_URL!, { maxRetriesPerRequest: null });

class BullQueue implements JobQueue {
  private q: Queue;
  private conn = connection();
  constructor() { this.q = new Queue(QUEUE_NAME, { connection: this.conn }); }
  async enqueue(jobId: string) {
    // jobId doubles as BullMQ id -> enqueueing twice cannot run the same job twice
    await this.q.add('analyze', { jobId }, { jobId, attempts: 2, backoff: { type: 'exponential', delay: 5000 },
      removeOnComplete: 1000, removeOnFail: 1000 });
  }
  async idle() {}
  async close() { await this.q.close(); await this.conn.quit(); }
  async stats() { return this.q.getJobCounts('waiting', 'active', 'delayed', 'failed', 'completed'); }
  async ping() { try { return (await this.conn.ping()) === 'PONG'; } catch { return false; } }
}

export const createQueue = (): JobQueue => (config().queueMode === 'bullmq' ? new BullQueue() : new InlineQueue());

/** Worker process entry (docker-compose `worker` service) or in-process for tests. */
export function startWorker(concurrency = 1) {
  const conn = connection();
  const w = new Worker(QUEUE_NAME, async (job) => runAnalysisJob(job.data.jobId), { connection: conn, concurrency });
  w.on('failed', (job, err) => console.error('[worker] job failed', job?.id, err.message));
  return { worker: w, close: async () => { await w.close(); await conn.quit(); } };
}
