import { config } from '../config';
import { purgeExpiredUploads } from '../services/analysis';
import { startWorker } from '../queues';

if (config().queueMode !== 'bullmq') throw new Error('Worker needs REDIS_URL (QUEUE_MODE=bullmq)');
const { close } = startWorker(Number(process.env.WORKER_CONCURRENCY ?? 1));
const timer = setInterval(() => purgeExpiredUploads().catch((e) => console.error('[purge]', e.message)), 60 * 60 * 1000);
console.log('[worker] started');
for (const sig of ['SIGINT', 'SIGTERM'] as const) process.on(sig, async () => { clearInterval(timer); await close(); process.exit(0); });
