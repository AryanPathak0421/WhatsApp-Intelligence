import { Router } from 'express';
import { z } from 'zod';
import { prisma } from '../db';
import { authenticate, projectAccess, requirePermission } from '../middlewares/auth';
import { audit, validateBody } from '../middlewares/misc';
import { AppError, asyncHandler, notFound } from '../utils/errors';
import { isAdmin } from '../utils/permissions';
import { maskPhone, decryptField } from '../utils/crypto';
import { can } from '../utils/permissions';

export const projectsRouter = Router();
projectsRouter.use(authenticate);

const projectBody = z.object({
  name: z.string().min(1).max(150), description: z.string().max(2000).nullish(), clientName: z.string().max(150).nullish(),
  startDate: z.coerce.date().nullish(), expectedDelivery: z.coerce.date().nullish(), timezone: z.string().max(60).optional(),
  dateOrderHint: z.enum(['DMY', 'MDY', 'YMD']).nullish(),
});

projectsRouter.get('/', asyncHandler(async (req, res) => {
  const where = isAdmin(req.user!.role) ? {} : { members: { some: { userId: req.user!.id, canView: true } } };
  const rows = await prisma.project.findMany({ where, orderBy: { createdAt: 'desc' }, include: { client: true,
    progress: { orderBy: { computedAt: 'desc' }, take: 1 }, health: { orderBy: { computedAt: 'desc' }, take: 1 } } });
  res.json({ items: rows.map((p) => ({ id: p.id, name: p.name, client: p.client?.name ?? null, status: p.status, startDate: p.startDate,
    expectedDelivery: p.expectedDelivery, progress: p.progress[0]?.overall ?? null, health: p.health[0] ? { score: p.health[0].score, status: p.health[0].status } : null })) });
}));

projectsRouter.post('/', requirePermission('project:create'), validateBody(projectBody), asyncHandler(async (req, res) => {
  const { clientName, ...rest } = req.body;
  const client = clientName ? await prisma.client.create({ data: { name: clientName } }) : null;
  const project = await prisma.project.create({ data: { ...rest, clientId: client?.id, managerId: req.user!.id,
    members: { create: { userId: req.user!.id, canView: true, canEdit: true } } } });
  await audit(req, 'CREATE_PROJECT', { entity: 'Project', entityId: project.id, projectId: project.id });
  res.status(201).json(project);
}));

projectsRouter.get('/:id', projectAccess('view'), asyncHandler(async (req, res) => {
  const p = await prisma.project.findUniqueOrThrow({ where: { id: req.params.id }, include: { client: true,
    members: { include: { user: { select: { id: true, name: true, email: true, role: true } } } } } });
  res.json(p);
}));

projectsRouter.put('/:id', requirePermission('project:edit'), projectAccess('edit'), validateBody(projectBody.partial()), asyncHandler(async (req, res) => {
  const { clientName, ...rest } = req.body;
  const p = await prisma.project.update({ where: { id: req.params.id }, data: rest });
  if (clientName && p.clientId) await prisma.client.update({ where: { id: p.clientId }, data: { name: clientName } });
  await audit(req, 'UPDATE_PROJECT', { entity: 'Project', entityId: p.id, projectId: p.id, meta: Object.keys(rest) });
  res.json(p);
}));

projectsRouter.delete('/:id', requirePermission('project:delete'), projectAccess('edit'), asyncHandler(async (req, res) => {
  await prisma.project.delete({ where: { id: req.params.id } });
  await audit(req, 'DELETE_PROJECT', { entity: 'Project', entityId: req.params.id });
  res.status(204).end();
}));

// ---- members (platform users with access to this project) --------------------
projectsRouter.get('/:id/members', projectAccess('view'), requirePermission('team:view'), asyncHandler(async (req, res) => {
  const rows = await prisma.projectMember.findMany({ where: { projectId: req.params.id }, include: { user: { select: { id: true, name: true, email: true, role: true } } } });
  res.json({ items: rows });
}));

projectsRouter.post('/:id/members', requirePermission('member:manage'), projectAccess('edit'),
  validateBody(z.object({ userId: z.string().uuid(), canEdit: z.boolean().default(false) })), asyncHandler(async (req, res) => {
    if (!(await prisma.user.findUnique({ where: { id: req.body.userId } }))) throw notFound('User');
    const m = await prisma.projectMember.upsert({ where: { projectId_userId: { projectId: req.params.id, userId: req.body.userId } },
      create: { projectId: req.params.id, ...req.body }, update: { canEdit: req.body.canEdit, canView: true } });
    await audit(req, 'CHANGE_MEMBER', { projectId: req.params.id, entity: 'ProjectMember', entityId: m.id, meta: { added: req.body.userId, canEdit: req.body.canEdit } });
    res.status(201).json(m);
  }));

projectsRouter.delete('/:id/members/:userId', requirePermission('member:manage'), projectAccess('edit'), asyncHandler(async (req, res) => {
  await prisma.projectMember.deleteMany({ where: { projectId: req.params.id, userId: req.params.userId } });
  await audit(req, 'CHANGE_MEMBER', { projectId: req.params.id, meta: { removed: req.params.userId } });
  res.status(204).end();
}));

// ---- chat participants ("team" detected from the conversation) ------------------
projectsRouter.get('/:id/team', projectAccess('view'), requirePermission('team:view'), asyncHandler(async (req, res) => {
  const reveal = can(req.user!.role, 'chat:view_raw') && ['SUPER_ADMIN', 'ADMIN', 'PROJECT_MANAGER'].includes(req.user!.role);
  const rows = await prisma.chatParticipant.findMany({ where: { projectId: req.params.id }, orderBy: { displayName: 'asc' },
    include: { _count: { select: { messages: true, assigned: true } } } });
  if (reveal) await audit(req, 'VIEW_SENSITIVE', { projectId: req.params.id, entity: 'ChatParticipant', meta: { phones: true } });
  res.json({ items: rows.map((p) => ({ id: p.id, name: p.displayName, role: p.role, roleConfidence: p.roleConfidence, roleSource: p.roleSource,
    team: p.team, isActive: p.isActive, messageCount: p._count.messages, taskCount: p._count.assigned,
    phone: p.phone ? (reveal ? decryptField(p.phone) : maskPhone(decryptField(p.phone))) : null })) });
}));

projectsRouter.put('/:id/team/:pid', requirePermission('team:edit'), projectAccess('edit'),
  validateBody(z.object({ role: z.enum(['PROJECT_MANAGER', 'DEVELOPER', 'FRONTEND_DEVELOPER', 'BACKEND_DEVELOPER', 'FULLSTACK_DEVELOPER', 'QA', 'DESIGNER',
    'SALES', 'CLIENT', 'CLIENT_REPRESENTATIVE', 'ADMIN', 'OTHER']).optional(), team: z.string().max(60).nullish(), isActive: z.boolean().optional(), email: z.string().email().nullish() })),
  asyncHandler(async (req, res) => {
    const p = await prisma.chatParticipant.findFirst({ where: { id: req.params.pid, projectId: req.params.id } });
    if (!p) throw notFound('Participant');
    const data: any = { ...req.body };
    if (req.body.role) { data.roleSource = 'admin'; data.roleConfidence = 1; } // manual role is never overwritten by re-analysis
    const upd = await prisma.chatParticipant.update({ where: { id: p.id }, data });
    if (req.body.role && req.body.role !== p.role) {
      await prisma.changeLog.create({ data: { projectId: p.projectId, entity: 'ChatParticipant', entityId: p.id, field: 'role', oldValue: p.role, newValue: req.body.role, changedById: req.user!.id } });
    }
    await audit(req, 'OVERRIDE_AI', { projectId: p.projectId, entity: 'ChatParticipant', entityId: p.id, meta: req.body });
    res.json({ id: upd.id, name: upd.displayName, role: upd.role, roleSource: upd.roleSource });
  }));
