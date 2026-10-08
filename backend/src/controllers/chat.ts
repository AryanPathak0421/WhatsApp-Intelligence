import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { Router } from 'express';
import { Prisma } from '@prisma/client';
import { z } from 'zod';
import { config } from '../config';
import { prisma } from '../db';
import { authenticate, projectAccess, requirePermission, viaEntity } from '../middlewares/auth';
import { audit, pageParams, upload, validateQuery } from '../middlewares/misc';
import { JobQueue } from '../queues';
import { ai } from '../services/aiClient';
import { encryptBuffer, sha256 } from '../utils/crypto';
import { extractFirstTxt, ZipError } from '../utils/zipText';
import { naive } from '../utils/time';
import { AppError, asyncHandler, badRequest, notFound } from '../utils/errors';

const MAX_EXPORT_BYTES = 200 * 1024 * 1024;     // cap on the text extracted from an uploaded .zip (decompression-bomb guard)
const HEADER = /^‎?(\[\s*\d{1,4}[/.\-]\d{1,2}[/.\-]\d{1,4},?\s+\d{1,2}[:.]\d{2}|\d{1,4}[/.\-]\d{1,2}[/.\-]\d{1,4},?\s+\d{1,2}[:.]\d{2}[^\n]{0,12}?\s[-–])/m;

/** Cheap pre-check before storing anything: plain text, not binary, contains WhatsApp-style message headers. */
export function looksLikeWhatsApp(buf: Buffer): boolean {
  if (!buf.length) return false;
  const head = buf.subarray(0, 256 * 1024);
  let text: string;
  if (head[0] === 0xff && head[1] === 0xfe) text = head.toString('utf16le');
  else {
    if (head.includes(0)) return false;
    text = head.toString('utf8');
  }
  return HEADER.test(text.replace(/[‎‏ ﻿]/g, (c) => (c === ' ' ? ' ' : '')));
}

const jobView = (j: any) => ({ id: j.id, projectId: j.projectId, uploadId: j.uploadId, status: j.status, stage: j.stage, progress: j.progress,
  error: j.error, createdAt: j.createdAt, startedAt: j.startedAt, finishedAt: j.finishedAt });

const msgQuery = z.object({
  limit: z.string().optional(), cursor: z.string().optional(), q: z.string().max(200).optional(), sender: z.string().max(100).optional(),
  from: z.coerce.date().optional(), to: z.coerce.date().optional(), taskId: z.string().max(100).optional(), includeSystem: z.enum(['true', 'false']).optional(),
});

export function chatRouter(queue: JobQueue) {
  const r = Router();
  r.use(authenticate);

  r.post('/projects/:id/chat/upload', requirePermission('chat:upload'), projectAccess('edit'), upload().single('file'),
    asyncHandler(async (req, res) => {
      const pid = req.params.id;
      if (!req.file) throw badRequest('Attach a WhatsApp .txt export in the "file" field');
      let buf = req.file.buffer;
      let uploadedName = req.file.originalname;
      if (/\.zip$/i.test(uploadedName)) {                          // WhatsApp's "Export chat" produces a .zip when media is included: read the chat text out of it
        try { const x = extractFirstTxt(buf, MAX_EXPORT_BYTES); buf = x.data; uploadedName = path.basename(x.name); }
        catch (e) { throw new AppError(422, 'INVALID_CHAT', e instanceof ZipError ? e.message : 'The ZIP could not be read'); }
      }
      if (!looksLikeWhatsApp(buf)) throw new AppError(422, 'INVALID_CHAT', 'This does not look like a WhatsApp chat export (.txt)');
      const hash = sha256(buf);
      const dup = await prisma.chatUpload.findUnique({ where: { projectId_sha256: { projectId: pid, sha256: hash } } });
      if (dup) throw new AppError(409, 'DUPLICATE_UPLOAD', 'This chat appears to have already been imported.', { uploadId: dup.id });
      const active = await prisma.analysisJob.findFirst({ where: { projectId: pid, status: { in: ['QUEUED', 'RUNNING'] } } });
      if (active) throw new AppError(409, 'ANALYSIS_IN_PROGRESS', 'An analysis is already running for this project', { jobId: active.id });

      const storageKey = crypto.randomUUID(); // never derived from the user-supplied name
      await fs.mkdir(config().UPLOAD_DIR, { recursive: true });
      await fs.writeFile(path.join(config().UPLOAD_DIR, storageKey), encryptBuffer(buf), { mode: 0o600 });
      const safeName = path.basename(uploadedName).replace(/[^\w.\- ]/g, '_').slice(0, 120);
      const up = await prisma.chatUpload.create({ data: { projectId: pid, uploadedById: req.user!.id, fileName: safeName, storageKey, sha256: hash,
        sizeBytes: BigInt(buf.length), status: 'QUEUED', purgeAfter: new Date(Date.now() + config().UPLOAD_TTL_HOURS * 3_600_000) } });
      const job = await prisma.analysisJob.create({ data: { projectId: pid, uploadId: up.id, status: 'QUEUED', stage: 'Uploading', progress: 5 } });
      await queue.enqueue(job.id);
      await audit(req, 'UPLOAD', { projectId: pid, entity: 'ChatUpload', entityId: up.id, meta: { bytes: buf.length } });
      res.status(202).json({ jobId: job.id, uploadId: up.id, status: 'QUEUED' });
    }));

  r.get('/projects/:id/chat/uploads', projectAccess('view'), requirePermission('chat:view_raw'), asyncHandler(async (req, res) => {
    const rows = await prisma.chatUpload.findMany({ where: { projectId: req.params.id }, orderBy: { createdAt: 'desc' },
      select: { id: true, fileName: true, status: true, messageCount: true, newMessageCount: true, firstMessageAt: true, lastMessageAt: true, createdAt: true, errorMessage: true, parseReport: true } });
    res.json({ items: rows });
  }));

  r.get('/analysis/:jobId', viaEntity((id) => prisma.analysisJob.findUnique({ where: { id }, select: { projectId: true } }), 'view', 'jobId'),
    asyncHandler(async (req, res) => res.json(jobView(await prisma.analysisJob.findUniqueOrThrow({ where: { id: req.params.jobId } })))));

  r.get('/projects/:id/chat/analysis', projectAccess('view'), asyncHandler(async (req, res) => {
    const j = await prisma.analysisJob.findFirst({ where: { projectId: req.params.id }, orderBy: { createdAt: 'desc' } });
    res.json(j ? jobView(j) : null);
  }));

  r.post('/projects/:id/chat/reanalyze', requirePermission('chat:upload'), projectAccess('edit'), asyncHandler(async (req, res) => {
    const pid = req.params.id;
    if (!(await prisma.chatMessage.count({ where: { projectId: pid } }))) throw badRequest('Upload a chat first');
    const active = await prisma.analysisJob.findFirst({ where: { projectId: pid, status: { in: ['QUEUED', 'RUNNING'] } } });
    if (active) throw new AppError(409, 'ANALYSIS_IN_PROGRESS', 'An analysis is already running for this project', { jobId: active.id });
    const job = await prisma.analysisJob.create({ data: { projectId: pid, status: 'QUEUED', stage: 'Queued', progress: 5 } });
    await queue.enqueue(job.id);
    await audit(req, 'REANALYZE', { projectId: pid, entity: 'AnalysisJob', entityId: job.id });
    res.status(202).json({ jobId: job.id, status: 'QUEUED' });
  }));

  r.get('/projects/:id/messages', projectAccess('view'), requirePermission('chat:view_raw'), validateQuery(msgQuery), asyncHandler(async (req, res) => {
    const q = (req as any).q as z.infer<typeof msgQuery>;
    const { limit, cursor } = pageParams(q);
    const where: Prisma.ChatMessageWhereInput = { projectId: req.params.id };
    if (q.includeSystem !== 'true') where.isSystem = false;
    if (q.q) where.text = { contains: q.q, mode: 'insensitive' };
    if (q.sender) where.sender = { displayName: q.sender };
    if (q.from || q.to) where.timestamp = { gte: q.from, lte: q.to };
    if (q.taskId) {
      const t = await prisma.task.findFirst({ where: { id: q.taskId, projectId: req.params.id }, select: { evidenceMessageIds: true } });
      where.id = { in: t?.evidenceMessageIds ?? [] };
    }
    const rows = await prisma.chatMessage.findMany({ where, orderBy: [{ timestamp: 'asc' }, { seq: 'asc' }], take: limit + 1,
      ...(cursor ? { cursor: { id: cursor }, skip: 1 } : {}), include: { sender: { select: { id: true, displayName: true } } } });
    const page = rows.slice(0, limit);
    await audit(req, 'VIEW_SENSITIVE', { projectId: req.params.id, entity: 'ChatMessage', meta: { count: page.length } });
    res.json({ items: page.map((m) => ({ id: m.id, seq: m.seq, timestamp: m.timestamp, sender: m.sender ? { id: m.sender.id, name: m.sender.displayName } : null,
      text: m.text, originalText: m.originalText, type: m.messageType, isMedia: m.isMedia, isDeleted: m.isDeleted, isEdited: m.isEdited, isForwarded: m.isForwarded, urls: m.urls })),
      nextCursor: rows.length > limit ? page.at(-1)!.id : null });
  }));

  /** Auditability: the exact WhatsApp messages (plus context) behind an extracted task. */
  r.get('/tasks/:id/evidence', viaEntity((id) => prisma.task.findUnique({ where: { id }, select: { projectId: true } }), 'view'),
    requirePermission('chat:view_raw'), asyncHandler(async (req, res) => {
      const t = await prisma.task.findUniqueOrThrow({ where: { id: req.params.id } });
      const ids = [...new Set([t.sourceMessageId, ...t.evidenceMessageIds].filter(Boolean) as string[])];
      const core = await prisma.chatMessage.findMany({ where: { projectId: t.projectId, id: { in: ids } }, orderBy: [{ timestamp: 'asc' }, { seq: 'asc' }], include: { sender: { select: { displayName: true } } } });
      const view = async (m: typeof core[number]) => ({ id: m.id, timestamp: m.timestamp, sender: m.sender?.displayName ?? null, text: m.text, isEvidence: ids.includes(m.id),
        context: (await prisma.chatMessage.findMany({ where: { projectId: t.projectId, seq: { in: [m.seq - 2, m.seq - 1, m.seq + 1, m.seq + 2] }, isSystem: false }, orderBy: { seq: 'asc' },
          select: { id: true, text: true, timestamp: true, sender: { select: { displayName: true } } } })).map((c) => ({ id: c.id, sender: c.sender?.displayName ?? null, text: c.text, timestamp: c.timestamp })) });
      await audit(req, 'VIEW_SENSITIVE', { projectId: t.projectId, entity: 'Task', entityId: t.id });
      res.json({ task: { id: t.id, title: t.title, status: t.status, confidence: t.confidence, reviewState: t.reviewState, statusEvidence: t.statusEvidence }, evidence: await Promise.all(core.map(view)) });
    }));

  r.get('/projects/:id/search', projectAccess('view'), requirePermission('chat:view_raw'), validateQuery(z.object({ q: z.string().min(1).max(300), k: z.string().optional(), mode: z.enum(['hybrid', 'semantic', 'lexical']).optional() })),
    asyncHandler(async (req, res) => {
      const q = (req as any).q;
      const body = { project_id: req.params.id, query: q.q, k: Math.min(parseInt(q.k ?? '8', 10) || 8, 30), mode: q.mode ?? 'hybrid' };
      let out = await ai.search(body);
      if (!out) { // ai-engine restarted / index not warm: re-index from the database (messages are the source of truth)
        const rows = await prisma.chatMessage.findMany({ where: { projectId: req.params.id, isSystem: false }, orderBy: [{ timestamp: 'asc' }, { seq: 'asc' }], select: { id: true, text: true, timestamp: true, sender: { select: { displayName: true } } } });
        const p = req.params.id;
        const msgs = rows.map((m, i) => ({ id: m.id.startsWith(p + ':') ? m.id.slice(p.length + 1) : m.id, text: m.text, sender: m.sender?.displayName ?? null, ts: naive(m.timestamp)!, index: i }));
        for (let i = 0; i < msgs.length; i += 2000) await ai.index(p, msgs.slice(i, i + 2000));
        out = await ai.search(body);
      }
      const hits = (out?.hits ?? []).map((h: any) => ({ ...h, message_id: `${req.params.id}:${h.message_id}`, context: h.context.map((c: any) => ({ ...c, message_id: `${req.params.id}:${c.message_id}` })) }));
      await audit(req, 'VIEW_SENSITIVE', { projectId: req.params.id, entity: 'Search' });
      res.json({ hits });
    }));

  return r;
}
