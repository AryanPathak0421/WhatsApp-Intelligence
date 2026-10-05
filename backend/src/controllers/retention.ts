import { Router } from 'express';
import { z } from 'zod';
import { prisma } from '../db';
import { authenticate, projectAccess, requirePermission } from '../middlewares/auth';
import { audit, validateBody } from '../middlewares/misc';
import { JobQueue } from '../queues';
import { eraseProjectData, purgeBefore } from '../services/retention';
import { asyncHandler, badRequest } from '../utils/errors';

const policy = z.object({ retentionDays: z.number().int().min(30).max(3650).nullable() });
const erase = z.object({ confirmProjectName: z.string().min(1).max(150) });

/** Per-project retention policy, on-demand purge, and full erasure of a project's conversation data. */
export function retentionRouter(queue: JobQueue) {
  const r = Router();

  r.get('/projects/:id/retention', authenticate, projectAccess('view'), requirePermission('project:edit'), asyncHandler(async (req, res) => {
    const p = await prisma.project.findUniqueOrThrow({ where: { id: req.params.id }, select: { retentionDays: true } });
    res.json({ retentionDays: p.retentionDays, options: [30, 90, 365], min: 30, max: 3650 });
  }));

  r.put('/projects/:id/retention', authenticate, requirePermission('project:edit'), projectAccess('edit'), validateBody(policy), asyncHandler(async (req, res) => {
    const before = await prisma.project.findUniqueOrThrow({ where: { id: req.params.id }, select: { retentionDays: true } });
    await prisma.project.update({ where: { id: req.params.id }, data: { retentionDays: req.body.retentionDays } });
    await audit(req, 'SET_RETENTION', { projectId: req.params.id, entity: 'Project', entityId: req.params.id, meta: { from: before.retentionDays, to: req.body.retentionDays } });
    res.json({ retentionDays: req.body.retentionDays });
  }));

  r.post('/projects/:id/retention/purge', authenticate, requirePermission('project:edit'), projectAccess('edit'), asyncHandler(async (req, res) => {
    const p = await prisma.project.findUniqueOrThrow({ where: { id: req.params.id }, select: { retentionDays: true } });
    if (p.retentionDays == null) throw badRequest('Set a retention period first');
    const result = await purgeBefore(req.params.id, new Date(Date.now() - p.retentionDays * 86_400_000), queue);
    await audit(req, 'PURGE_RETENTION', { projectId: req.params.id, entity: 'Project', entityId: req.params.id, meta: { ...result } });
    res.json(result);
  }));

  /** Irreversible. Requires the project delete permission AND the project's exact name, so it cannot be triggered by a stray click or a guessed id. */
  r.post('/projects/:id/erase-data', authenticate, requirePermission('project:delete'), projectAccess('edit'), validateBody(erase), asyncHandler(async (req, res) => {
    const p = await prisma.project.findUniqueOrThrow({ where: { id: req.params.id }, select: { name: true } });
    if (req.body.confirmProjectName !== p.name) throw badRequest('The confirmation name does not match this project');
    await audit(req, 'ERASE_PROJECT_DATA', { projectId: req.params.id, entity: 'Project', entityId: req.params.id });
    res.json(await eraseProjectData(req.params.id));
  }));

  return r;
}
