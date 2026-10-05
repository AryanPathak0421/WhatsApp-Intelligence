import { Router } from 'express';
import { prisma } from '../db';
import { authenticate, requirePermission } from '../middlewares/auth';
import { ai } from '../services/aiClient';
import { autoImportStatus, pendingByFolder, scaffoldFolders } from '../services/autoimport';
import { JobQueue } from '../queues';
import { asyncHandler } from '../utils/errors';

/**
 * Liveness vs readiness.
 *  /api/health  process is up (no dependencies)           public, nothing but a boolean
 *  /api/ready   database + queue + AI engine are usable   public, booleans only (no versions, URLs or counts)
 *  /api/queue/status, /api/ai/status                      admin only: depths, job states, model versions
 */
export function statusRouter(queue: JobQueue) {
  const r = Router();
  r.get('/health', (_req, res) => res.json({ status: 'ok' }));

  r.get('/ready', asyncHandler(async (_req, res) => {
    const [db, q, engine] = await Promise.all([
      prisma.$queryRaw`SELECT 1`.then(() => true, () => false),
      queue.ping().catch(() => false),
      ai.status().then((s) => s.reachable),
    ]);
    const ready = db && q;                                   // the AI engine being down degrades analysis but the app can still serve data
    res.status(ready ? 200 : 503).json({ status: ready ? (engine ? 'ready' : 'degraded') : 'not_ready', db, queue: q, ai: engine });
  }));

  r.get('/queue/status', authenticate, requirePermission('user:manage'), asyncHandler(async (_req, res) => {
    const [depth, jobs] = await Promise.all([
      queue.stats(),
      prisma.analysisJob.groupBy({ by: ['status'], _count: { _all: true } }),
    ]);
    const oldest = await prisma.analysisJob.findFirst({ where: { status: { in: ['QUEUED', 'RUNNING'] } }, orderBy: { createdAt: 'asc' }, select: { createdAt: true, status: true } });
    res.json({ mode: depth ? 'bullmq' : 'inline', depth, jobsByStatus: Object.fromEntries(jobs.map((j) => [j.status, j._count._all])),
      oldestActive: oldest ? { status: oldest.status, ageSeconds: Math.round((Date.now() - oldest.createdAt.getTime()) / 1000) } : null });
  }));

  r.get('/ai/status', authenticate, requirePermission('user:manage'), asyncHandler(async (_req, res) => {
    const s = await ai.status();
    res.status(s.reachable ? 200 : 503).json(s);
  }));
  /** Watched-folder import (exports synced from the phone). Admin only; shows the folder, each project folder's state, and recent outcomes. */
  r.get('/auto-import/status', authenticate, requirePermission('user:manage'), asyncHandler(async (_req, res) => {
    const s = autoImportStatus();
    res.json({ ...s, folders: s.enabled ? await pendingByFolder() : [] });
  }));

  r.post('/auto-import/folders', authenticate, requirePermission('user:manage'), asyncHandler(async (_req, res) => {
    if (!autoImportStatus().enabled) return void res.status(409).json({ error: { code: 'AUTO_IMPORT_DISABLED', message: 'Set AUTO_IMPORT_DIR to enable the watched folder' } });
    res.json(await scaffoldFolders());
  }));
  return r;
}
