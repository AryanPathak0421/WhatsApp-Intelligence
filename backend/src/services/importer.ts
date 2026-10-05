import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { config } from '../config';
import { prisma } from '../db';
import { looksLikeWhatsApp } from '../controllers/chat';
import { JobQueue } from '../queues';
import { encryptBuffer, sha256 } from '../utils/crypto';

export type ImportOutcome =
  | { status: 'queued'; uploadId: string; jobId: string }
  | { status: 'duplicate'; uploadId: string }
  | { status: 'busy' }
  | { status: 'invalid'; reason: string };

/**
 * Same steps as POST /projects/:id/chat/upload, for callers that are not an HTTP request (the watched folder):
 * pre-check it is a WhatsApp export, refuse an identical file already imported, never start a second analysis, store the file encrypted, queue the job.
 */
export async function importChatBuffer(o: { projectId: string; userId: string; buffer: Buffer; fileName: string; queue: JobQueue; source: string }): Promise<ImportOutcome> {
  const { projectId, userId, buffer, queue } = o;
  if (!looksLikeWhatsApp(buffer)) return { status: 'invalid', reason: 'This does not look like a WhatsApp chat export (.txt)' };
  const hash = sha256(buffer);
  const dup = await prisma.chatUpload.findUnique({ where: { projectId_sha256: { projectId, sha256: hash } } });
  if (dup) return { status: 'duplicate', uploadId: dup.id };
  if (await prisma.analysisJob.findFirst({ where: { projectId, status: { in: ['QUEUED', 'RUNNING'] } } })) return { status: 'busy' };

  const storageKey = crypto.randomUUID();                                   // never derived from the file name
  await fs.mkdir(config().UPLOAD_DIR, { recursive: true });
  await fs.writeFile(path.join(config().UPLOAD_DIR, storageKey), encryptBuffer(buffer), { mode: 0o600 });
  const safeName = path.basename(o.fileName).replace(/[^\w.\- ]/g, '_').slice(0, 120);
  const up = await prisma.chatUpload.create({ data: { projectId, uploadedById: userId, fileName: safeName, storageKey, sha256: hash, sizeBytes: BigInt(buffer.length), status: 'QUEUED',
    purgeAfter: new Date(Date.now() + config().UPLOAD_TTL_HOURS * 3_600_000) } });
  const job = await prisma.analysisJob.create({ data: { projectId, uploadId: up.id, status: 'QUEUED', stage: 'Uploading', progress: 5 } });
  await queue.enqueue(job.id);
  await prisma.auditLog.create({ data: { userId, projectId, action: 'AUTO_IMPORT', entity: 'ChatUpload', entityId: up.id, meta: { bytes: buffer.length, source: o.source } } }).catch(() => undefined);
  return { status: 'queued', uploadId: up.id, jobId: job.id };
}
