/**
 * Retention and erasure. "Deleting a chat" must also delete what was derived from it, so every purge covers:
 * raw messages (and, by cascade, their enrichments and embeddings), the AI engine's in-memory search index, derived analysis rows, analysis snapshots,
 * reports and notifications. Audit logs are kept on purpose (they record that a purge happened, not the content).
 *
 * Two operations:
 *  - purgeBefore(project, cutoff)  drop messages older than the cutoff, drop superseded snapshots/reports/notifications, then re-analyse what is
 *                                  left so derived rows no longer mention deleted messages. Human-confirmed rows are NOT auto-deleted (a person
 *                                  decided to keep them): they are counted and returned so someone can review them.
 *  - eraseProjectData(project)     remove everything derived from or stored of the conversation, keeping only the project shell, members and audit.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import { config } from '../config';
import { prisma } from '../db';
import { JobQueue } from '../queues';
import { ai } from './aiClient';
import { scheduleReanalysis } from './reanalysis';

export interface PurgeResult {
  messagesDeleted: number;
  remainingMessages: number;
  snapshotsDeleted: number;
  reportsDeleted: number;
  notificationsDeleted: number;
  humanEditedItemsRetained: number;
  derivedWiped: boolean;
  reanalysisScheduled: boolean;
  searchIndexDropped: boolean;
}

const HUMAN = ['HUMAN_CONFIRMED', 'HUMAN_CORRECTED'] as const;

/** Delete every derived row of a project (children first). Participants are personal data too, so they go when nothing references them. */
async function wipeDerived(pid: string, tx: Omit<typeof prisma, '$connect' | '$disconnect' | '$on' | '$transaction' | '$use' | '$extends'>) {
  await tx.task.deleteMany({ where: { projectId: pid } });                       // cascades TaskHistory / TaskAssignment
  await tx.requirement.deleteMany({ where: { projectId: pid } });                // cascades RequirementChange
  for (const m of ['clientPendingItem', 'salesActivity', 'decision', 'meeting', 'commitment', 'deadline', 'bug', 'conflict', 'risk', 'projectEvent', 'projectProgress',
    'projectHealth', 'insight', 'aIAnalysis', 'report', 'notification', 'projectModule'] as const) {
    await (tx as any)[m].deleteMany({ where: { projectId: pid } });
  }
}

export async function purgeBefore(pid: string, cutoff: Date, queue?: JobQueue): Promise<PurgeResult> {
  const messages = await prisma.chatMessage.deleteMany({ where: { projectId: pid, timestamp: { lt: cutoff } } });
  await prisma.roomMessage.deleteMany({ where: { room: { projectId: pid }, createdAt: { lt: cutoff } } });      // in-app chat copies
  const remaining = await prisma.chatMessage.count({ where: { projectId: pid } });
  let snapshots = 0, wiped = false;
  if (remaining === 0) {
    await prisma.$transaction(async (tx) => { await wipeDerived(pid, tx as any); });
    wiped = true;
  } else if (messages.count > 0) {
    // keep only the newest snapshot per kind; older ones still contain text derived from messages that no longer exist
    const kinds = await prisma.aIAnalysis.groupBy({ by: ['kind'], where: { projectId: pid } });
    for (const { kind } of kinds) {
      const keep = await prisma.aIAnalysis.findFirst({ where: { projectId: pid, kind }, orderBy: { createdAt: 'desc' }, select: { id: true } });
      snapshots += (await prisma.aIAnalysis.deleteMany({ where: { projectId: pid, kind, id: { not: keep!.id } } })).count;
    }
  }
  const reports = await prisma.report.deleteMany({ where: { projectId: pid, createdAt: { lt: cutoff } } });
  const notes = await prisma.notification.deleteMany({ where: { projectId: pid, createdAt: { lt: cutoff } } });
  const human = await prisma.task.count({ where: { projectId: pid, reviewState: { in: [...HUMAN] } } });
  const dropped = messages.count > 0 ? await ai.dropIndex(pid) : false;
  let scheduled = false;
  if (queue && messages.count > 0 && remaining > 0) { scheduleReanalysis(pid, queue, 0); scheduled = true; }
  return { messagesDeleted: messages.count, remainingMessages: remaining, snapshotsDeleted: snapshots, reportsDeleted: reports.count, notificationsDeleted: notes.count,
    humanEditedItemsRetained: wiped ? 0 : human, derivedWiped: wiped, reanalysisScheduled: scheduled, searchIndexDropped: dropped };
}

export async function eraseProjectData(pid: string): Promise<PurgeResult & { uploadFilesDeleted: number }> {
  const uploads = await prisma.chatUpload.findMany({ where: { projectId: pid, storageKey: { notIn: ['', 'webhook', 'inapp'] } }, select: { id: true, storageKey: true } });
  for (const u of uploads) await fs.rm(path.join(config().UPLOAD_DIR, u.storageKey), { force: true });
  let messages = 0;
  await prisma.$transaction(async (tx) => {
    messages = (await tx.chatMessage.deleteMany({ where: { projectId: pid } })).count;
    await tx.roomMessage.deleteMany({ where: { room: { projectId: pid } } });
    await wipeDerived(pid, tx as any);
    await tx.analysisJob.deleteMany({ where: { projectId: pid } });
    await tx.chatParticipant.deleteMany({ where: { projectId: pid } });
    await tx.chatUpload.deleteMany({ where: { projectId: pid, storageKey: { not: 'inapp' } } });      // the in-app chat keeps its (empty) carrier upload
  }, { timeout: 120_000 });
  const dropped = await ai.dropIndex(pid);
  return { messagesDeleted: messages, remainingMessages: 0, snapshotsDeleted: 0, reportsDeleted: 0, notificationsDeleted: 0, humanEditedItemsRetained: 0, derivedWiped: true,
    reanalysisScheduled: false, searchIndexDropped: dropped, uploadFilesDeleted: uploads.length };
}

/** Applies each project's retentionDays. Safe to run repeatedly; does nothing for projects without a policy. */
export async function runRetentionSweep(queue?: JobQueue, now = new Date()): Promise<{ projects: number; messagesDeleted: number }> {
  const projects = await prisma.project.findMany({ where: { retentionDays: { not: null } }, select: { id: true, retentionDays: true } });
  let deleted = 0;
  for (const p of projects) {
    const cutoff = new Date(now.getTime() - p.retentionDays! * 86_400_000);
    deleted += (await purgeBefore(p.id, cutoff, queue)).messagesDeleted;
  }
  return { projects: projects.length, messagesDeleted: deleted };
}
