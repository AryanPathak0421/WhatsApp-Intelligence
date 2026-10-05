import { Router } from 'express';
import { Prisma } from '@prisma/client';
import { z } from 'zod';
import { prisma } from '../db';
import { authenticate, projectAccess, requirePermission, viaEntity } from '../middlewares/auth';
import { audit, pageParams, validateBody, validateQuery } from '../middlewares/misc';
import { asyncHandler, forbidden } from '../utils/errors';
import { can } from '../utils/permissions';

export const analyticsRouter = Router();
analyticsRouter.use(authenticate);
const clientSafe = (role: any) => !can(role, 'analytics:view');
const latest = <T>(rows: T[]) => rows[0] ?? null;

analyticsRouter.get('/projects/:id/progress', projectAccess('view'), requirePermission('client_facing:view'), asyncHandler(async (req, res) => {
  const wantHistory = req.query.history === 'true';
  const wantExplain = req.query.explain === 'true' && !clientSafe(req.user!.role);
  const rows = await prisma.projectProgress.findMany({ where: { projectId: req.params.id }, orderBy: { computedAt: 'desc' }, take: wantHistory ? 30 : 1,
    omit: { explanation: !wantExplain } });   // the explanation JSON is large; only read it when asked
  const p = latest(rows);
  if (!p) return res.json(null);
  const safe = clientSafe(req.user!.role);
  const out: any = { computedAt: p.computedAt, overall: p.overall, development: p.development, design: p.design, testing: p.testing, deployment: p.deployment,
    clientApproval: p.clientApproval, documentation: p.documentation, completedWeight: p.completedWeight, totalWeight: p.totalWeight };
  if (wantExplain) out.explanation = p.explanation; // "Why N%?" (task-level detail is internal)
  if (wantHistory) out.history = rows.map((r) => ({ computedAt: r.computedAt, overall: r.overall }));
  res.json(out);
}));

analyticsRouter.get('/projects/:id/health', projectAccess('view'), requirePermission('client_facing:view'), asyncHandler(async (req, res) => {
  const h = latest(await prisma.projectHealth.findMany({ where: { projectId: req.params.id }, orderBy: { computedAt: 'desc' }, take: 1 }));
  if (!h) return res.json(null);
  res.json(clientSafe(req.user!.role) ? { score: h.score, status: h.status, computedAt: h.computedAt } : { score: h.score, status: h.status, components: h.components, computedAt: h.computedAt });
}));

const snapshot = async (projectId: string, kind: string) =>
  latest(await prisma.aIAnalysis.findMany({ where: { projectId, kind }, orderBy: { createdAt: 'desc' }, take: 1 }));

analyticsRouter.get('/projects/:id/team-performance', projectAccess('view'), requirePermission('analytics:view', 'team:view'), asyncHandler(async (req, res) => {
  const s = await snapshot(req.params.id, 'CONTRIBUTION');
  const data: any = s?.result ?? { contribution: [], sales: [], communication: {} };
  res.json({ computedAt: s?.createdAt ?? null, developers: data.contribution, communication: data.communication });
}));

analyticsRouter.get('/projects/:id/sales', projectAccess('view'), requirePermission('sales:view'), asyncHandler(async (req, res) => {
  const s = await snapshot(req.params.id, 'CONTRIBUTION');
  res.json({ items: (s?.result as any)?.sales ?? [] });
}));

analyticsRouter.get('/projects/:id/client-response-time', projectAccess('view'), requirePermission('analytics:view'), asyncHandler(async (req, res) => {
  res.json((await snapshot(req.params.id, 'CLIENT_RESPONSE_TIME'))?.result ?? null);
}));

analyticsRouter.get('/projects/:id/velocity', projectAccess('view'), requirePermission('analytics:view'), asyncHandler(async (req, res) => {
  res.json((await snapshot(req.params.id, 'VELOCITY'))?.result ?? null);
}));

const qaQuery = z.object({ status: z.enum(['ANSWERED', 'POSSIBLY_ANSWERED', 'UNANSWERED']).optional(), limit: z.string().optional() });

/** Question/answer analytics: counts and response times are arithmetic over evidence-scored matches; POSSIBLY_ANSWERED is never counted as answered. */
analyticsRouter.get('/projects/:id/qa', projectAccess('view'), requirePermission('analytics:view'), validateQuery(qaQuery), asyncHandler(async (req, res) => {
  const q = (req as any).q as z.infer<typeof qaQuery>;
  const s = await snapshot(req.params.id, 'QA');
  const data: any = s?.result ?? { items: [], stats: null };
  const limit = Math.min(Number(q.limit) || 100, 500);
  const items = (data.items ?? []).filter((i: any) => !q.status || i.status === q.status).slice(0, limit);
  res.json({ computedAt: s?.createdAt ?? null, stats: data.stats, method: data.method, items });
}));

/** Sentiment / frustration / urgency from a lexicon baseline. Model inference, not ground truth; each item lists the cues it used. */
analyticsRouter.get('/projects/:id/sentiment', projectAccess('view'), requirePermission('analytics:view'), asyncHandler(async (req, res) => {
  const s = await snapshot(req.params.id, 'SENTIMENT');
  res.json({ computedAt: s?.createdAt ?? null, ...((s?.result as object) ?? { counts: null, items: [] }) });
}));

const periodQuery = z.object({ kind: z.enum(['daily', 'weekly', 'monthly']).default('weekly'), limit: z.string().optional() });

/** Hierarchical daily/weekly/monthly summaries; every highlight carries its source message ids. */
analyticsRouter.get('/projects/:id/summaries', projectAccess('view'), requirePermission('analytics:view'), validateQuery(periodQuery), asyncHandler(async (req, res) => {
  const q = (req as any).q as z.infer<typeof periodQuery>;
  const s = await snapshot(req.params.id, 'PERIODIC');
  const all: any[] = ((s?.result as any)?.[q.kind] as any[]) ?? [];
  const limit = Math.min(Number(q.limit) || 30, 120);
  res.json({ computedAt: s?.createdAt ?? null, kind: q.kind, method: (s?.result as any)?.method ?? null, items: all.slice(-limit).reverse() });
}));

const cpQuery = z.object({ type: z.enum(['APPROVAL', 'FEEDBACK', 'CREDENTIALS', 'CONTENT', 'PAYMENT', 'REQUIREMENT', 'UAT', 'PRODUCTION', 'OTHER']).optional(),
  status: z.enum(['OPEN', 'RESOLVED', 'CANCELLED']).optional(), limit: z.string().optional(), cursor: z.string().optional() });

analyticsRouter.get('/projects/:id/client-pending', projectAccess('view'), requirePermission('client_facing:view'), validateQuery(cpQuery), asyncHandler(async (req, res) => {
  const q = (req as any).q as z.infer<typeof cpQuery>;
  const { limit, cursor } = pageParams(q);
  const rows = await prisma.clientPendingItem.findMany({ where: { projectId: req.params.id, type: q.type, status: q.status }, take: limit + 1,
    orderBy: [{ waitingSince: 'asc' }, { id: 'asc' }], ...(cursor ? { cursor: { id: cursor }, skip: 1 } : {}), include: { task: { select: { id: true, title: true } } } });
  const now = Date.now();
  res.json({ items: rows.slice(0, limit).map((c) => ({ id: c.id, title: c.title, type: c.type, responsible: c.responsible, requestedAt: c.requestedAt, waitingSince: c.waitingSince,
    ageDays: Math.round(((c.resolvedAt ?? new Date()).getTime() - c.waitingSince.getTime()) / 8640000) / 10, priority: c.priority, impact: c.impact, status: c.status,
    resolvedAt: c.resolvedAt, task: c.task, confidence: c.confidence, needsReview: c.reviewState === 'NEEDS_REVIEW', sourceMessageIds: c.sourceMessageIds, _now: undefined })),
    nextCursor: rows.length > limit ? rows[limit - 1].id : null });
}));

analyticsRouter.put('/client-pending/:id', viaEntity((id) => prisma.clientPendingItem.findUnique({ where: { id }, select: { projectId: true } }), 'edit'),
  validateBody(z.object({ title: z.string().min(1).max(300).optional(), status: z.enum(['OPEN', 'RESOLVED', 'CANCELLED']).optional(),
    priority: z.enum(['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']).optional(), impact: z.enum(['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']).optional(),
    type: z.enum(['APPROVAL', 'FEEDBACK', 'CREDENTIALS', 'CONTENT', 'PAYMENT', 'REQUIREMENT', 'UAT', 'PRODUCTION', 'OTHER']).optional() })),
  asyncHandler(async (req, res) => {
    if (!(can(req.user!.role, 'task:edit') || can(req.user!.role, 'sales:view')) || req.user!.role === 'CLIENT_VIEWER') throw forbidden();
    const old = await prisma.clientPendingItem.findUniqueOrThrow({ where: { id: req.params.id } });
    const data: any = { ...req.body, reviewState: 'HUMAN_CORRECTED' };
    if (req.body.status === 'RESOLVED' && old.status !== 'RESOLVED') data.resolvedAt = new Date();
    if (req.body.status === 'OPEN') data.resolvedAt = null;
    const upd = await prisma.$transaction(async (tx) => {
      for (const k of Object.keys(req.body)) {
        if (String((old as any)[k]) !== String(req.body[k])) {
          await tx.changeLog.create({ data: { projectId: old.projectId, entity: 'ClientPendingItem', entityId: old.id, field: k, oldValue: (old as any)[k] as never, newValue: req.body[k], changedById: req.user!.id } });
        }
      }
      return tx.clientPendingItem.update({ where: { id: old.id }, data });
    });
    await audit(req, 'OVERRIDE_AI', { projectId: old.projectId, entity: 'ClientPendingItem', entityId: old.id, meta: req.body });
    res.json(upd);
  }));

analyticsRouter.get('/projects/:id/risks', projectAccess('view'), requirePermission('risk:view'), asyncHandler(async (req, res) => {
  const [items, summary] = await Promise.all([
    prisma.risk.findMany({ where: { projectId: req.params.id, isOpen: true }, orderBy: [{ score: 'desc' }, { detectedAt: 'desc' }], take: 200 }),   // top 200; the summary carries the totals
    snapshot(req.params.id, 'RISK_SUMMARY')]);
  res.json({ summary: summary?.result ?? null, items });
}));

analyticsRouter.get('/projects/:id/conflicts', projectAccess('view'), requirePermission('analytics:view'), asyncHandler(async (req, res) => {
  res.json({ items: await prisma.conflict.findMany({ where: { projectId: req.params.id }, orderBy: { detectedAt: 'desc' } }) });
}));

const CLIENT_EVENTS = ['COMPLETED', 'CLIENT_PENDING', 'CLIENT_RESOLVED', 'DEPLOYMENT', 'MEETING', 'START'];
analyticsRouter.get('/projects/:id/timeline', projectAccess('view'), requirePermission('client_facing:view'), asyncHandler(async (req, res) => {
  const where: Prisma.ProjectEventWhereInput = { projectId: req.params.id, ...(clientSafe(req.user!.role) ? { type: { in: CLIENT_EVENTS } } : {}) };
  res.json({ items: await prisma.projectEvent.findMany({ where, orderBy: { occurredAt: 'asc' }, select: { id: true, occurredAt: true, type: true, title: true, sourceMessageIds: !clientSafe(req.user!.role) } }) });
}));

analyticsRouter.get('/projects/:id/insights', projectAccess('view'), requirePermission('analytics:view'), asyncHandler(async (req, res) => {
  const kind = typeof req.query.kind === 'string' ? req.query.kind : undefined;
  res.json({ items: await prisma.insight.findMany({ where: { projectId: req.params.id, kind }, orderBy: { createdAt: 'asc' } }) });
}));

analyticsRouter.get('/projects/:id/summary', projectAccess('view'), requirePermission('client_facing:view'), asyncHandler(async (req, res) => {
  const rows = await prisma.insight.findMany({ where: { projectId: req.params.id, kind: 'SUMMARY' }, orderBy: { createdAt: 'asc' } });
  res.json({ text: rows.map((r) => r.text).join(' '), claims: clientSafe(req.user!.role) ? undefined : rows.map((r) => ({ text: r.text, evidence: r.evidence })) });
}));

// ---- notifications & audit ----------------------------------------------------------
analyticsRouter.get('/notifications', asyncHandler(async (req, res) => {
  const items = await prisma.notification.findMany({ where: { userId: req.user!.id, ...(req.query.unread === 'true' ? { readAt: null } : {}) }, orderBy: { createdAt: 'desc' }, take: 100 });
  res.json({ items, unread: await prisma.notification.count({ where: { userId: req.user!.id, readAt: null } }) });
}));
analyticsRouter.post('/notifications/:id/read', asyncHandler(async (req, res) => {
  await prisma.notification.updateMany({ where: { id: req.params.id, userId: req.user!.id }, data: { readAt: new Date() } });
  res.status(204).end();
}));
analyticsRouter.post('/notifications/read-all', asyncHandler(async (req, res) => {
  await prisma.notification.updateMany({ where: { userId: req.user!.id, readAt: null }, data: { readAt: new Date() } });
  res.status(204).end();
}));
analyticsRouter.get('/audit', requirePermission('audit:view'), asyncHandler(async (req, res) => {
  const { limit, cursor } = pageParams(req.query as any);
  const where: Prisma.AuditLogWhereInput = { projectId: typeof req.query.projectId === 'string' ? req.query.projectId : undefined, action: typeof req.query.action === 'string' ? req.query.action : undefined };
  const rows = await prisma.auditLog.findMany({ where, take: limit + 1, orderBy: [{ createdAt: 'desc' }, { id: 'asc' }], ...(cursor ? { cursor: { id: cursor }, skip: 1 } : {}) });
  res.json({ items: rows.slice(0, limit), nextCursor: rows.length > limit ? rows[limit - 1].id : null });
}));
