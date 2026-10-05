import { Router } from 'express';
import { Prisma } from '@prisma/client';
import { z } from 'zod';
import { prisma } from '../db';
import { authenticate, projectAccess, requirePermission, viaEntity } from '../middlewares/auth';
import { audit, pageParams, validateBody, validateQuery } from '../middlewares/misc';
import { AppError, asyncHandler, forbidden, notFound } from '../utils/errors';
import { can } from '../utils/permissions';

export const tasksRouter = Router();
tasksRouter.use(authenticate);

const STATUS = z.enum(['TODO', 'IN_PROGRESS', 'COMPLETED', 'BLOCKED', 'CANCELLED']);
const PRIORITY = z.enum(['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']);
const editable = z.object({
  title: z.string().min(1).max(300), description: z.string().max(4000).nullish(), status: STATUS, priority: PRIORITY,
  assigneeId: z.string().uuid().nullish(), deadline: z.coerce.date().nullish(), weight: z.number().min(0.5).max(20),
  externalDependency: z.string().max(200).nullish(),
});
const listQuery = z.object({ limit: z.string().optional(), cursor: z.string().optional(), status: STATUS.optional(), assigneeId: z.string().optional(),
  needsReview: z.enum(['true', 'false']).optional(), overdue: z.enum(['true', 'false']).optional() });

const view = (t: any, clientSafe: boolean) => clientSafe
  ? { id: t.id, title: t.title, status: t.status, deadline: t.deadline, completedAt: t.completedAt }
  : { id: t.id, title: t.title, description: t.description, status: t.status, priority: t.priority, domain: t.domain, weight: t.weight, deadline: t.deadline,
      deadlineText: t.deadlineText, completedAt: t.completedAt, confidence: t.confidence, reviewState: t.reviewState, needsReview: t.reviewState === 'NEEDS_REVIEW',
      externalDependency: t.externalDependency, assignee: t.assignee ? { id: t.assignee.id, name: t.assignee.displayName } : null,
      createdBy: t.createdBy ? { id: t.createdBy.id, name: t.createdBy.displayName } : null, sourceMessageId: t.sourceMessageId,
      evidenceCount: t.evidenceMessageIds.length, modelVersion: t.modelVersion, createdAt: t.createdAt };

tasksRouter.get('/projects/:id/tasks', projectAccess('view'), validateQuery(listQuery), asyncHandler(async (req, res) => {
  const q = (req as any).q as z.infer<typeof listQuery>;
  const { limit, cursor } = pageParams(q);
  const where: Prisma.TaskWhereInput = { projectId: req.params.id };
  if (q.status) where.status = q.status;
  if (q.assigneeId) where.assigneeId = q.assigneeId;
  if (q.needsReview === 'true') where.reviewState = 'NEEDS_REVIEW';
  if (q.overdue === 'true') Object.assign(where, { deadline: { lt: new Date() }, status: { notIn: ['COMPLETED', 'CANCELLED'] } });
  const rows = await prisma.task.findMany({ where, take: limit + 1, orderBy: [{ createdAt: 'asc' }, { id: 'asc' }], ...(cursor ? { cursor: { id: cursor }, skip: 1 } : {}),
    include: { assignee: true, createdBy: true } });
  const clientSafe = !can(req.user!.role, 'analytics:view');
  res.json({ items: rows.slice(0, limit).map((t) => view(t, clientSafe)), nextCursor: rows.length > limit ? rows[limit - 1].id : null });
}));

tasksRouter.post('/projects/:id/tasks', requirePermission('task:edit'), projectAccess('edit'),
  validateBody(editable.partial().required({ title: true })), asyncHandler(async (req, res) => {
    const t = await prisma.task.create({ data: { projectId: req.params.id, ...req.body, reviewState: 'HUMAN_CONFIRMED', confidence: 1, weightSource: 'manual', createdAt: new Date() }, include: { assignee: true, createdBy: true } });
    await prisma.taskHistory.create({ data: { taskId: t.id, field: 'created', newValue: t.title, changedBy: req.user!.id } });
    await audit(req, 'CREATE_TASK', { projectId: t.projectId, entity: 'Task', entityId: t.id });
    res.status(201).json(view(t, false));
  }));

/** Human override. Writes TaskHistory + ChangeLog (who/when/old/new) and protects the row from re-analysis. */
tasksRouter.put('/tasks/:id', viaEntity((id) => prisma.task.findUnique({ where: { id }, select: { projectId: true } }), 'view'),
  validateBody(editable.partial().refine((o) => Object.keys(o).length > 0, 'No fields to update')), asyncHandler(async (req, res) => {
    const task = await prisma.task.findUniqueOrThrow({ where: { id: req.params.id } });
    const keys = Object.keys(req.body);
    const role = req.user!.role;
    if (!can(role, 'task:edit')) {
      // team members / sales may only change the status of tasks (and only on projects they can edit)
      if (!can(role, 'task:status') || keys.some((k) => k !== 'status')) throw forbidden();
      if (!req.access!.canEdit) throw forbidden('Read-only access to this project');
    }
    if (req.body.assigneeId && !(await prisma.chatParticipant.findFirst({ where: { id: req.body.assigneeId, projectId: task.projectId } }))) throw notFound('Assignee');
    const changes = keys.filter((k) => String((task as any)[k] ?? '') !== String(req.body[k] ?? '') && (k !== 'deadline' || (task.deadline?.getTime() ?? 0) !== (req.body.deadline?.getTime() ?? 0)));
    const data: any = { ...req.body, reviewState: 'HUMAN_CORRECTED' };
    if (req.body.status === 'COMPLETED' && task.status !== 'COMPLETED') data.completedAt = new Date();
    if (req.body.status && req.body.status !== 'COMPLETED') data.completedAt = null;
    if (keys.includes('weight')) data.weightSource = 'manual';
    const upd = await prisma.$transaction(async (tx) => {
      for (const k of changes) {
        await tx.taskHistory.create({ data: { taskId: task.id, field: k, oldValue: String((task as any)[k] ?? ''), newValue: String(req.body[k] ?? ''), changedBy: req.user!.id } });
        await tx.changeLog.create({ data: { projectId: task.projectId, entity: 'Task', entityId: task.id, field: k, oldValue: ((task as any)[k] ?? null) as never,
          newValue: (req.body[k] ?? null) as never, changedById: req.user!.id } });
      }
      return tx.task.update({ where: { id: task.id }, data, include: { assignee: true, createdBy: true } });
    });
    await audit(req, keys.includes('status') ? 'CHANGE_STATUS' : 'UPDATE_TASK', { projectId: task.projectId, entity: 'Task', entityId: task.id, meta: { fields: changes } });
    res.json(view(upd, false));
  }));

tasksRouter.delete('/tasks/:id', requirePermission('task:delete'), viaEntity((id) => prisma.task.findUnique({ where: { id }, select: { projectId: true } }), 'edit'),
  asyncHandler(async (req, res) => {
    const t = await prisma.task.delete({ where: { id: req.params.id } });
    await audit(req, 'DELETE_TASK', { projectId: t.projectId, entity: 'Task', entityId: t.id, meta: { title: t.title } });
    res.status(204).end();
  }));

tasksRouter.get('/tasks/:id/history', viaEntity((id) => prisma.task.findUnique({ where: { id }, select: { projectId: true } }), 'view'),
  requirePermission('analytics:view'), asyncHandler(async (req, res) => {
    res.json({ items: await prisma.taskHistory.findMany({ where: { taskId: req.params.id }, orderBy: { changedAt: 'desc' } }) });
  }));
