import { config } from '../config';
import { startWorker } from '../queues';

if (config().queueMode !== 'bullmq') throw new Error('Worker needs REDIS_URL (QUEUE_MODE=bullmq)');
const { close } = startWorker(Number(process.env.WORKER_CONCURRENCY ?? 1));
console.log('[worker] started');
for (const sig of ['SIGINT', 'SIGTERM'] as const) process.on(sig, async () => { await close(); process.exit(0); });
