/**
 * Authorized WhatsApp ingestion (Cloud API webhooks). What this can and cannot do is set by Meta, not by us:
 *  - it receives messages for conversations of a BUSINESS phone number: groups created through the Groups API, and 1:1 chats with customers;
 *  - it cannot read existing consumer WhatsApp groups and has no history backfill (see docx/01-analysis);
 *  - media are recorded as metadata only (media ids are not guaranteed for group messages, and nothing is downloaded here).
 * Security: the payload is accepted only with a valid HMAC-SHA256 signature over the RAW body; only conversations an authorized user has mapped to a
 * project are stored (everything else is dropped and only counted); ingestion is idempotent per WhatsApp message id.
 */
import crypto from 'node:crypto';
import { prisma } from '../db';
import { config } from '../config';
import { encryptField } from '../utils/crypto';
import { JobQueue } from '../queues';

export type UnifiedType = 'text' | 'image' | 'audio' | 'video' | 'document' | 'sticker' | 'reaction' | 'unsupported';

/** The source-independent message shape the rest of the system works with. */
export interface UnifiedMessage {
  messageId: string;
  source: 'whatsapp';
  phoneNumberId: string;
  conversationId: string;            // group_id, or the customer's wa_id for 1:1
  isGroup: boolean;
  senderId: string;                  // wa_id
  senderName: string;
  timestamp: Date;                   // true UTC instant
  messageType: UnifiedType;
  text: string;
  replyTo: string | null;
  media: { kind: string; mimeType?: string; caption?: string } | null;
  reaction: { targetMessageId: string; emoji: string } | null;
}

export function verifySignature(raw: Buffer, header: string | undefined, secret: string): boolean {
  if (!header || !header.startsWith('sha256=')) return false;
  const given = Buffer.from(header.slice(7), 'hex');
  const want = crypto.createHmac('sha256', secret).update(raw).digest();
  return given.length === want.length && crypto.timingSafeEqual(given, want);
}

const MEDIA_KINDS = ['image', 'audio', 'video', 'document', 'sticker'] as const;

/** Pure: Cloud API webhook body -> unified messages. Status updates and unknown shapes are skipped, never thrown on. */
export function normalizeCloudPayload(body: any): UnifiedMessage[] {
  const out: UnifiedMessage[] = [];
  for (const entry of Array.isArray(body?.entry) ? body.entry : []) {
    for (const change of Array.isArray(entry?.changes) ? entry.changes : []) {
      const v = change?.value;
      const phoneNumberId = v?.metadata?.phone_number_id;
      if (!phoneNumberId || !Array.isArray(v?.messages)) continue;
      const names = new Map<string, string>((v.contacts ?? []).map((c: any) => [String(c.wa_id), String(c.profile?.name ?? '')]));
      for (const m of v.messages) {
        if (!m?.id || !m?.from || !m?.timestamp) continue;
        const ts = new Date(Number(m.timestamp) * 1000);
        if (Number.isNaN(ts.getTime())) continue;
        const groupId = m.group_id ? String(m.group_id) : null;
        const from = String(m.from);
        const base = { messageId: String(m.id), source: 'whatsapp' as const, phoneNumberId: String(phoneNumberId), conversationId: groupId ?? from, isGroup: Boolean(groupId),
          senderId: from, senderName: names.get(from) || from, timestamp: ts, replyTo: m.context?.id ? String(m.context.id) : null };
        const kind = String(m.type ?? '');
        if (kind === 'text') out.push({ ...base, messageType: 'text', text: String(m.text?.body ?? ''), media: null, reaction: null });
        else if ((MEDIA_KINDS as readonly string[]).includes(kind)) {
          const caption = m[kind]?.caption ? String(m[kind].caption) : undefined;
          out.push({ ...base, messageType: kind as UnifiedType, text: caption ? `<Media omitted>\n${caption}` : '<Media omitted>', media: { kind, mimeType: m[kind]?.mime_type, caption }, reaction: null });
        } else if (kind === 'reaction') {
          out.push({ ...base, messageType: 'reaction', text: '', media: null, reaction: { targetMessageId: String(m.reaction?.message_id ?? ''), emoji: String(m.reaction?.emoji ?? '') } });
        } else out.push({ ...base, messageType: 'unsupported', text: '', media: null, reaction: null });
      }
    }
  }
  return out;
}

/** WhatsApp sends UTC instants; the rest of the system stores wall-clock-as-UTC in the project's timezone (same as exported chats). */
export function toWallClock(ts: Date, timeZone: string): Date {
  const parts = new Intl.DateTimeFormat('en-GB', { timeZone, hour12: false, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
    .formatToParts(ts).reduce<Record<string, string>>((a, p) => { a[p.type] = p.value; return a; }, {});
  const hour = parts.hour === '24' ? '00' : parts.hour;
  return new Date(`${parts.year}-${parts.month}-${parts.day}T${hour}:${parts.minute}:${parts.second}.000Z`);
}

const stableId = (pid: string, waId: string) => `${pid}:wa_${crypto.createHash('sha1').update(waId).digest('hex').slice(0, 20)}`;

const chain = new Map<string, Promise<unknown>>();                  // serialises writes per project (seq numbers, participant creation)
const serial = <T,>(key: string, fn: () => Promise<T>): Promise<T> => {
  const next = (chain.get(key) ?? Promise.resolve()).then(fn, fn);
  chain.set(key, next.catch(() => undefined));
  return next;
};

export interface IngestResult { received: number; stored: number; duplicates: number; unmapped: number; ignored: number; projects: string[] }

export async function ingest(msgs: UnifiedMessage[], queue?: JobQueue): Promise<IngestResult> {
  const res: IngestResult = { received: msgs.length, stored: 0, duplicates: 0, unmapped: 0, ignored: 0, projects: [] };
  const sources = new Map<string, Awaited<ReturnType<typeof prisma.whatsappSource.findFirst>>>();
  const touched = new Set<string>();
  for (const m of msgs) {
    if (m.messageType === 'reaction' || m.messageType === 'unsupported') { res.ignored++; continue; }      // reactions are not stored yet (inbound support unverified)
    const key = `${m.phoneNumberId}|${m.conversationId}`;
    if (!sources.has(key)) sources.set(key, await prisma.whatsappSource.findFirst({ where: { phoneNumberId: m.phoneNumberId, conversationKey: m.conversationId, active: true } }));
    const src = sources.get(key);
    if (!src) { res.unmapped++; continue; }                                                                // never store conversations nobody authorized
    const stored = await serial(src.projectId, async () => {
      const project = await prisma.project.findUnique({ where: { id: src.projectId }, select: { timezone: true } });
      let part = await prisma.chatParticipant.findFirst({ where: { projectId: src.projectId, displayName: m.senderName } });
      part ??= await prisma.chatParticipant.create({ data: { projectId: src.projectId, displayName: m.senderName, phone: encryptField(m.senderId) } });
      const last = await prisma.chatMessage.aggregate({ where: { projectId: src.projectId }, _max: { seq: true } });
      const isMedia = m.messageType !== 'text';
      const r = await prisma.chatMessage.createMany({ skipDuplicates: true, data: [{
        id: stableId(src.projectId, m.messageId), projectId: src.projectId, uploadId: src.uploadId, seq: (last._max.seq ?? -1) + 1, senderId: part.id,
        timestamp: toWallClock(m.timestamp, project?.timezone ?? 'Asia/Kolkata'), originalText: m.text, text: m.text, messageType: isMedia ? 'MEDIA' : 'TEXT', isMedia,
        urls: m.text.match(/https?:\/\/\S+/g) ?? [], replyToId: m.replyTo ? stableId(src.projectId, m.replyTo) : null }] });
      if (r.count) await prisma.whatsappSource.update({ where: { id: src.id }, data: { lastEventAt: new Date(), messageCount: { increment: 1 } } });
      return r.count;
    });
    if (stored) { res.stored++; touched.add(src.projectId); } else res.duplicates++;
  }
  res.projects = [...touched];
  if (queue) for (const pid of touched) scheduleReanalysis(pid, queue);
  return res;
}

// ---- debounced incremental re-analysis: many messages in a short burst cause ONE analysis job ----
const timers = new Map<string, { timer: NodeJS.Timeout; first: number }>();
const MAX_WAIT_MS = 5 * 60_000;

export function scheduleReanalysis(projectId: string, queue: JobQueue, debounceMs = config().WEBHOOK_DEBOUNCE_MS): void {
  const prev = timers.get(projectId);
  const first = prev?.first ?? Date.now();
  if (prev) clearTimeout(prev.timer);
  const wait = Math.max(0, Math.min(debounceMs, MAX_WAIT_MS - (Date.now() - first)));       // a constant stream cannot postpone analysis forever
  timers.set(projectId, { first, timer: setTimeout(() => void fire(projectId, queue, debounceMs), wait) });
}

async function fire(projectId: string, queue: JobQueue, debounceMs: number): Promise<void> {
  timers.delete(projectId);
  try {
    const active = await prisma.analysisJob.findFirst({ where: { projectId, status: { in: ['QUEUED', 'RUNNING'] } } });
    if (active) { scheduleReanalysis(projectId, queue, Math.max(debounceMs, 5_000)); return; }   // never run two analyses of one project at once
    const job = await prisma.analysisJob.create({ data: { projectId, status: 'QUEUED', stage: 'Queued', progress: 5 } });
    await queue.enqueue(job.id);
  } catch (e) { console.error('[whatsapp] could not schedule analysis', (e as Error).message); }
}

export const _timersForTests = timers;
