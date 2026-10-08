import cors from 'cors';
import express from 'express';
import helmet from 'helmet';
import { config } from './config';
import { prisma } from './db';
import { analyticsRouter } from './controllers/analytics';
import { authRouter } from './controllers/auth';
import { chatRouter } from './controllers/chat';
import { eventsRouter } from './controllers/events';
import { googleRouter } from './controllers/google';
import { overviewRouter } from './controllers/overview';
import { projectsRouter } from './controllers/projects';
import { reportsRouter } from './controllers/reports';
import { retentionRouter } from './controllers/retention';
import { statusRouter } from './controllers/status';
import { whatsappRouter } from './controllers/whatsapp';
import { tasksRouter } from './controllers/tasks';
import { requestLog } from './middlewares/requestLog';
import { JobQueue } from './queues';
import { errorHandler } from './utils/errors';

export function createApp(queue: JobQueue, log?: (line: string) => void) {
  const app = express();
  app.disable('x-powered-by');
  app.set('trust proxy', config().TRUST_PROXY);
  app.use(requestLog(log));   // default writer: one JSON line to stdout
  app.use(helmet({ hsts: { maxAge: 31_536_000, includeSubDomains: true } })); // HTTPS is terminated by the reverse proxy
  app.use(cors({ origin: config().CORS_ORIGIN.split(','), credentials: true }));
  app.use('/api/webhooks/whatsapp', express.raw({ type: () => true, limit: '1mb' }));   // raw bytes: the signature is computed over them
  app.use(express.json({ limit: '1mb' }));

  app.get('/health', async (_req, res) => {
    try { await prisma.$queryRaw`SELECT 1`; res.json({ status: 'ok' }); }
    catch { res.status(503).json({ status: 'degraded', db: false }); }
  });
  app.use('/api', statusRouter(queue), whatsappRouter(queue), retentionRouter(queue), googleRouter(queue));
  app.use('/api/auth', authRouter);
  app.use('/api/projects', projectsRouter);
  app.use('/api', chatRouter(queue), tasksRouter, analyticsRouter, reportsRouter, overviewRouter, eventsRouter);
  app.use((_req, res) => res.status(404).json({ error: { code: 'NOT_FOUND', message: 'Route not found' } }));
  app.use(errorHandler);
  return app;
}
