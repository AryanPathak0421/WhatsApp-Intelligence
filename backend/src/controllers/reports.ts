import { Router } from 'express';
import { z } from 'zod';
import { prisma } from '../db';
import { authenticate, projectAccess, requirePermission, viaEntity } from '../middlewares/auth';
import { audit, validateBody } from '../middlewares/misc';
import { ai } from '../services/aiClient';
import { naive } from '../utils/time';
import { AppError, asyncHandler, badRequest } from '../utils/errors';

export const reportsRouter = Router();
reportsRouter.use(authenticate);

const body = z.object({ kind: z.enum(['FULL', 'DAILY', 'WEEKLY']).default('FULL'), periodEnd: z.coerce.date().optional(),
  company: z.string().max(150).optional() });

reportsRouter.post('/projects/:id/reports/generate', requirePermission('report:generate'), projectAccess('edit'), validateBody(body), asyncHandler(async (req, res) => {
  const pid = req.params.id;
  const project = await prisma.project.findUniqueOrThrow({ where: { id: pid }, include: { client: true } });
  const manager = project.managerId ? await prisma.user.findUnique({ where: { id: project.managerId } }) : null;
  const rows = await prisma.chatMessage.findMany({ where: { projectId: pid, isSystem: false, ...(req.body.periodEnd ? { timestamp: { lte: req.body.periodEnd } } : {}) },
    orderBy: [{ timestamp: 'asc' }, { seq: 'asc' }], select: { id: true, text: true, timestamp: true, sender: { select: { displayName: true } } } });
  if (!rows.length) throw badRequest('Nothing to report on yet: upload and analyze a chat first');
  const roles = await prisma.chatParticipant.findMany({ where: { projectId: pid, roleSource: 'admin' } });
  const content = await ai.report({
    messages: rows.map((m, i) => ({ id: m.id.startsWith(pid + ':') ? m.id.slice(pid.length + 1) : m.id, text: m.text, sender: m.sender?.displayName ?? null, ts: naive(m.timestamp)!, index: i })),
    role_overrides: Object.fromEntries(roles.map((r) => [r.displayName, r.role])), as_of: naive(req.body.periodEnd),
    project_start: naive(project.startDate), expected_delivery: naive(project.expectedDelivery),
    meta: { name: project.name, client: project.client?.name, manager: manager?.name, company: req.body.company, start_date: naive(project.startDate),
      expected_delivery: naive(project.expectedDelivery), generated_at: naive(new Date()) },
  });
  const rep = await prisma.report.create({ data: { projectId: pid, generatedBy: req.user!.id, kind: req.body.kind, periodEnd: req.body.periodEnd, content } });
  await audit(req, 'GENERATE_REPORT', { projectId: pid, entity: 'Report', entityId: rep.id, meta: { kind: req.body.kind } });
  res.status(201).json({ id: rep.id, kind: rep.kind, createdAt: rep.createdAt });
}));

reportsRouter.get('/projects/:id/reports', projectAccess('view'), requirePermission('report:view'), asyncHandler(async (req, res) => {
  res.json({ items: await prisma.report.findMany({ where: { projectId: req.params.id }, orderBy: { createdAt: 'desc' }, select: { id: true, kind: true, createdAt: true, generatedBy: true, periodEnd: true } }) });
}));

const FORMATS = { pdf: 'application/pdf', xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', csv: 'text/csv' } as const;

reportsRouter.get('/reports/:id', viaEntity((id) => prisma.report.findUnique({ where: { id }, select: { projectId: true } }), 'view'), requirePermission('report:view'),
  asyncHandler(async (req, res) => {
    const rep = await prisma.report.findUniqueOrThrow({ where: { id: req.params.id } });
    const format = String(req.query.format ?? 'json');
    await audit(req, 'VIEW_REPORT', { projectId: rep.projectId, entity: 'Report', entityId: rep.id, meta: { format } });
    if (format === 'json') return res.json({ id: rep.id, kind: rep.kind, createdAt: rep.createdAt, content: rep.content });
    if (!(format in FORMATS)) throw new AppError(422, 'BAD_FORMAT', 'format must be json, pdf, xlsx or csv');
    const out = await ai.exportReport(rep.content, format, typeof req.query.section === 'string' ? req.query.section : undefined);
    res.setHeader('Content-Type', FORMATS[format as keyof typeof FORMATS]);
    res.setHeader('Content-Disposition', `attachment; filename="report-${rep.id.slice(0, 8)}.${format}"`);
    res.send(out.data);
  }));
