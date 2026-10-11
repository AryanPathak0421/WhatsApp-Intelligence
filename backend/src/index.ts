import { createApp } from './app';
import { config } from './config';
import { assertUtf8, prisma } from './db';
import { createQueue } from './queues';
import { runRetentionSweep } from './services/retention';

assertUtf8().catch((e) => { console.error('[startup]', e.message); process.exit(1); });
const queue = createQueue();
const app = createApp(queue);
const server = app.listen(config().PORT, () => console.log(`[api] listening on :${config().PORT} (queue: ${config().queueMode})`));
const retention = setInterval(() => runRetentionSweep(queue).catch((e) => console.error('[retention]', e.message)), 6 * 60 * 60 * 1000);
for (const sig of ['SIGINT', 'SIGTERM'] as const) {
  process.on(sig, async () => { clearInterval(retention); server.close(); await queue.close(); await prisma.$disconnect(); process.exit(0); });
}
