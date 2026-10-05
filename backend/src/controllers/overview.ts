import { Router } from 'express';
import { Prisma } from '@prisma/client';
import { prisma } from '../db';
import { authenticate, projectAccess, requirePermission } from '../middlewares/auth';
import { asyncHandler } from '../utils/errors';
import { can, isAdmin } from '../utils/permissions';

export const overviewRouter = Router();
overviewRouter.use(authenticate);

const OPEN_BUG = ['OPEN', 'INVESTIGATING', 'IN_PROGRESS', 'REOPENED'] as const;
const NOT_DONE = ['COMPLETED', 'CANCELLED'] as const;

async function projectMetrics(projectId: string, internal: boolean) {
  const now = new Date();
  const [byStatus, overdue, needsReview, cpOpen, participants, messages, lastJob] = await Promise.all([
    prisma.task.groupBy({ by: ['status'], where: { projectId }, _count: true }),
    prisma.task.count({ where: { projectId, status: { notIn: [...NOT_DONE] }, deadline: { lt: now } } }),
    prisma.task.count({ where: { projectId, reviewState: 'NEEDS_REVIEW' } }),
    prisma.clientPendingItem.count({ where: { projectId, status: 'OPEN' } }),
    prisma.chatParticipant.count({ where: { projectId } }),
    prisma.chatMessage.count({ where: { projectId, isSystem: false } }),
    prisma.analysisJob.findFirst({ where: { projectId }, orderBy: { createdAt: 'desc' }, select: { id: true, status: true, stage: true, progress: true, finishedAt: true } }),
  ]);
  const tasks = { TODO: 0, IN_PROGRESS: 0, COMPLETED: 0, BLOCKED: 0, CANCELLED: 0 } as Record<string, number>;
  byStatus.forEach((g) => { tasks[g.status] = g._count; });
  const out: any = { tasks, overdue, clientPendingOpen: cpOpen, messages, lastAnalysis: lastJob };
  if (internal) {
    const [bugs, risks] = await Promise.all([
      prisma.bug.count({ where: { projectId, status: { in: [...OPEN_BUG] } } }),
      prisma.risk.groupBy({ by: ['severity'], where: { projectId, isOpen: true }, _count: true }),
    ]);
    const rs = { LOW: 0, MEDIUM: 0, HIGH: 0, CRITICAL: 0 } as Record<string, number>;
    risks.forEach((g) => { rs[g.severity] = g._count; });
    Object.assign(out, { openBugs: bugs, risksBySeverity: rs, needsReview, participants });
  }
  return out;
}

overviewRouter.get('/projects/:id/overview', projectAccess('view'), requirePermission('client_facing:view'), asyncHandler(async (req, res) => {
  const internal = can(req.user!.role, 'analytics:view');
  const p = await prisma.project.findUniqueOrThrow({ where: { id: req.params.id }, include: { client: true } });
  const manager = p.managerId ? await prisma.user.findUnique({ where: { id: p.managerId }, select: { id: true, name: true } }) : null;
  const [progress, health] = await Promise.all([
    prisma.projectProgress.findFirst({ where: { projectId: p.id }, orderBy: { computedAt: 'desc' } }),
    prisma.projectHealth.findFirst({ where: { projectId: p.id }, orderBy: { computedAt: 'desc' } }),
  ]);
  res.json({
    project: { id: p.id, name: p.name, description: p.description, status: p.status, client: p.client?.name ?? null, manager, startDate: p.startDate,
      expectedDelivery: p.expectedDelivery },
    progress: progress && { overall: progress.overall, development: progress.development, design: progress.design, testing: progress.testing,
      deployment: progress.deployment, clientApproval: progress.clientApproval, documentation: progress.documentation, computedAt: progress.computedAt },
    health: health && { score: health.score, status: health.status },
    ...(await projectMetrics(p.id, internal)),
  });
}));

/** Company-level dashboard + project comparison over every project the caller can access. */
overviewRouter.get('/executive', requirePermission('analytics:view'), asyncHandler(async (req, res) => {
  const where: Prisma.ProjectWhereInput = isAdmin(req.user!.role) ? {} : { members: { some: { userId: req.user!.id, canView: true } } };
  const projects = await prisma.project.findMany({ where, orderBy: { name: 'asc' }, include: { client: true } });
  const rows = await Promise.all(projects.map(async (p) => {
    const [progress, health, m] = await Promise.all([
      prisma.projectProgress.findFirst({ where: { projectId: p.id }, orderBy: { computedAt: 'desc' }, select: { overall: true } }),
      prisma.projectHealth.findFirst({ where: { projectId: p.id }, orderBy: { computedAt: 'desc' }, select: { score: true, status: true } }),
      projectMetrics(p.id, true),
    ]);
    return { id: p.id, name: p.name, client: p.client?.name ?? null, status: p.status, expectedDelivery: p.expectedDelivery,
      progress: progress?.overall ?? null, health, openClientPending: m.clientPendingOpen, overdue: m.overdue, blocked: m.tasks.BLOCKED,
      openBugs: m.openBugs, highRisks: m.risksBySeverity.HIGH + m.risksBySeverity.CRITICAL, messages: m.messages };
  }));
  const ids = projects.map((p) => p.id);
  const topRisks = await prisma.risk.findMany({ where: { projectId: { in: ids }, isOpen: true, severity: { in: ['HIGH', 'CRITICAL'] } },
    orderBy: [{ score: 'desc' }, { detectedAt: 'desc' }], take: 10, include: { project: { select: { id: true, name: true } } } });
  const assigned = await prisma.task.groupBy({ by: ['assigneeId', 'status'], where: { projectId: { in: ids }, assigneeId: { not: null }, status: { not: 'CANCELLED' } }, _count: true });
  const people = new Set(assigned.map((a) => a.assigneeId)), busy = new Set(assigned.filter((a) => a.status !== 'COMPLETED').map((a) => a.assigneeId));
  const withProgress = rows.filter((r) => r.progress !== null);
  res.json({
    totals: { projects: rows.length, active: rows.filter((r) => r.status === 'ACTIVE').length,
      atRisk: rows.filter((r) => r.health?.status === 'AT_RISK').length, critical: rows.filter((r) => ['CRITICAL', 'BLOCKED'].includes(r.health?.status ?? '')).length,
      averageProgress: withProgress.length ? Math.round((withProgress.reduce((s, r) => s + r.progress!, 0) / withProgress.length) * 10) / 10 : null,
      clientPending: rows.reduce((s, r) => s + r.openClientPending, 0), overdue: rows.reduce((s, r) => s + r.overdue, 0),
      blockers: rows.reduce((s, r) => s + r.blocked, 0), teamUtilization: people.size ? Math.round((100 * busy.size) / people.size) : null },
    projects: rows,
    topRisks: topRisks.map((r) => ({ id: r.id, title: r.title, severity: r.severity, project: r.project, recommendedAction: r.recommendedAction })),
  });
}));

overviewRouter.get('/users', requirePermission('user:manage'), asyncHandler(async (_req, res) => {
  res.json({ items: await prisma.user.findMany({ select: { id: true, name: true, email: true, role: true, isActive: true }, orderBy: { name: 'asc' } }) });
}));
