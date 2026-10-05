import { createApp } from './app';
import { config } from './config';
import { assertUtf8, prisma } from './db';
import { createQueue } from './queues';
import { purgeExpiredUploads } from './services/analysis';
import { startAutoImport } from './services/autoimport';
import { runRetentionSweep } from './services/retention';

assertUtf8().catch((e) => { console.error('[startup]', e.message); process.exit(1); });
const queue = createQueue();
const app = createApp(queue);
const server = app.listen(config().PORT, () => console.log(`[api] listening on :${config().PORT} (queue: ${config().queueMode})`));
const purge = setInterval(() => purgeExpiredUploads().catch((e) => console.error('[purge]', e.message)), 60 * 60 * 1000);
const retention = setInterval(() => runRetentionSweep(queue).catch((e) => console.error('[retention]', e.message)), 6 * 60 * 60 * 1000);
const stopAutoImport = startAutoImport(queue);
for (const sig of ['SIGINT', 'SIGTERM'] as const) {
  process.on(sig, async () => { clearInterval(purge); clearInterval(retention); stopAutoImport(); server.close(); await queue.close(); await prisma.$disconnect(); process.exit(0); });
}
