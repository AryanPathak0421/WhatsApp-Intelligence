import crypto from 'node:crypto';
import { Router } from 'express';
import { z } from 'zod';
import { config } from '../config';
import { prisma } from '../db';
import { authenticate, projectAccess, requirePermission } from '../middlewares/auth';
import { audit, validateBody } from '../middlewares/misc';
import { JobQueue } from '../queues';
import { ingest, normalizeCloudPayload, verifySignature } from '../services/whatsapp';
import { AppError, asyncHandler, notFound } from '../utils/errors';

const safeEqual = (a: string, b: string) => { const x = Buffer.from(a), y = Buffer.from(b); return x.length === y.length && crypto.timingSafeEqual(x, y); };

const sourceBody = z.object({
  phoneNumberId: z.string().regex(/^\d{5,32}$/, 'Meta phone_number_id (digits)'),
  conversationKey: z.string().min(3).max(64).regex(/^[\w@.\-]+$/, 'group_id or wa_id'),
  label: z.string().min(1).max(120),
});

/**
 * Public:  GET/POST /api/webhooks/whatsapp   (Meta verification handshake + signed event delivery; the raw body is needed for the signature,
 *          see app.ts where express.raw is mounted for this path before the JSON parser).
 * Private: /api/projects/:id/whatsapp-sources  map a conversation of a business number to a project. Nothing from an unmapped conversation is stored.
 */
export function whatsappRouter(queue: JobQueue) {
  const r = Router();

  r.get('/webhooks/whatsapp', (req, res) => {
    const token = config().WHATSAPP_VERIFY_TOKEN;
    if (!token) return void res.status(503).json({ error: { code: 'WEBHOOK_DISABLED', message: 'WhatsApp webhook is not configured' } });
    const given = String(req.query['hub.verify_token'] ?? '');
    if (req.query['hub.mode'] === 'subscribe' && given && safeEqual(given, token)) return void res.status(200).type('text/plain').send(String(req.query['hub.challenge'] ?? ''));
    res.status(403).json({ error: { code: 'FORBIDDEN', message: 'Verification failed' } });
  });

  r.post('/webhooks/whatsapp', asyncHandler(async (req, res) => {
    const secret = config().WHATSAPP_APP_SECRET;
    if (!secret) throw new AppError(503, 'WEBHOOK_DISABLED', 'WhatsApp webhook is not configured');
    const raw = req.body as Buffer;
    if (!Buffer.isBuffer(raw) || !raw.length) throw new AppError(400, 'BAD_REQUEST', 'Empty body');
    if (!verifySignature(raw, req.get('x-hub-signature-256'), secret)) throw new AppError(401, 'BAD_SIGNATURE', 'Invalid signature');
    let body: unknown;
    try { body = JSON.parse(raw.toString('utf8')); } catch { throw new AppError(400, 'BAD_REQUEST', 'Body is not JSON'); }
    const out = await ingest(normalizeCloudPayload(body), queue);
    res.status(200).json({ received: out.received, stored: out.stored, duplicates: out.duplicates, unmapped: out.unmapped, ignored: out.ignored });   // 200 so Meta does not retry
  }));

  r.get('/projects/:id/whatsapp-sources', authenticate, projectAccess('view'), requirePermission('chat:upload'), asyncHandler(async (req, res) => {
    const items = await prisma.whatsappSource.findMany({ where: { projectId: req.params.id }, orderBy: { createdAt: 'desc' },
      select: { id: true, phoneNumberId: true, conversationKey: true, label: true, active: true, createdAt: true, lastEventAt: true, messageCount: true } });
    res.json({ items });
  }));

  r.post('/projects/:id/whatsapp-sources', authenticate, requirePermission('chat:upload'), projectAccess('edit'), validateBody(sourceBody), asyncHandler(async (req, res) => {
    const pid = req.params.id;
    const b = req.body as z.infer<typeof sourceBody>;
    if (await prisma.whatsappSource.findUnique({ where: { phoneNumberId_conversationKey: { phoneNumberId: b.phoneNumberId, conversationKey: b.conversationKey } } })) {
      throw new AppError(409, 'ALREADY_MAPPED', 'This conversation is already connected');          // does not reveal which project owns it
    }
    const upload = await prisma.chatUpload.create({ data: { projectId: pid, uploadedById: req.user!.id, fileName: `WhatsApp Cloud API: ${b.label}`, storageKey: 'webhook',
      sha256: crypto.createHash('sha256').update(`webhook:${b.phoneNumberId}:${b.conversationKey}`).digest('hex'), sizeBytes: 0, status: 'COMPLETED' } });
    const src = await prisma.whatsappSource.create({ data: { projectId: pid, ...b, uploadId: upload.id, createdById: req.user!.id } });
    await audit(req, 'CONNECT_WHATSAPP_SOURCE', { projectId: pid, entity: 'WhatsappSource', entityId: src.id });
    res.status(201).json({ id: src.id, phoneNumberId: src.phoneNumberId, conversationKey: src.conversationKey, label: src.label, active: src.active });
  }));

  r.delete('/projects/:id/whatsapp-sources/:sid', authenticate, requirePermission('chat:upload'), projectAccess('edit'), asyncHandler(async (req, res) => {
    const src = await prisma.whatsappSource.findFirst({ where: { id: req.params.sid, projectId: req.params.id } });
    if (!src) throw notFound('Source');
    await prisma.whatsappSource.update({ where: { id: src.id }, data: { active: false } });     // stop ingesting; stored messages stay (deletion is a retention action)
    await audit(req, 'DISCONNECT_WHATSAPP_SOURCE', { projectId: req.params.id, entity: 'WhatsappSource', entityId: src.id });
    res.status(204).end();
  }));

  return r;
}
