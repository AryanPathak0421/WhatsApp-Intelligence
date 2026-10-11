/**
 * In-app chat. Users talk to each other inside the application: no WhatsApp number, no Meta API, no external service.
 *  - GROUP room with a project: every message is also written as a ChatMessage of that project (sender = a ChatParticipant linked to the user), so the normal
 *    analysis (tasks, progress, health, summaries) covers live conversation exactly like an imported chat, and a debounced re-analysis is scheduled.
 *  - GROUP room without a project: plain group chat, not analysed.
 *  - DIRECT room: private between two people, no project, never analysed.
 * Live delivery: an event with ids only (no text) goes to the room's members through the existing SSE stream; the client fetches the text over the API.
 */
import crypto from 'node:crypto';
import { prisma } from '../db';
import { events } from '../events/bus';
import { JobQueue } from '../queues';
import { scheduleReanalysis, serial, toWallClock } from './reanalysis';

export const MAX_TEXT = 4000;
export const directKey = (a: string, b: string) => [a, b].sort().join(':');
const mirroredId = (projectId: string, roomMessageId: string) => `${projectId}:app_${roomMessageId}`;

export async function memberIds(roomId: string): Promise<string[]> {
  return (await prisma.roomMember.findMany({ where: { roomId }, select: { userId: true } })).map((m) => m.userId);
}

export async function notifyRoom(room: { id: string; projectId: string | null }, type: 'chat.message' | 'chat.room'): Promise<void> {
  events.publish({ type, projectId: room.projectId ?? '', roomId: room.id, userIds: await memberIds(room.id) });
}

/** The carrier upload every in-app message of a project hangs on (ChatMessage requires one). Created once per project. */
async function carrierUpload(projectId: string, userId: string): Promise<string> {
  const sha256 = crypto.createHash('sha256').update(`inapp:${projectId}`).digest('hex');
  const found = await prisma.chatUpload.findUnique({ where: { projectId_sha256: { projectId, sha256 } }, select: { id: true } });
  if (found) return found.id;
  return (await prisma.chatUpload.create({ data: { projectId, uploadedById: userId, fileName: 'In-app chat', storageKey: 'inapp', sha256, sizeBytes: 0, status: 'COMPLETED' } })).id;
}

/** Sender as a project participant: reuse the participant with the same display name (e.g. from an imported chat) and link it to the account. */
async function participantFor(projectId: string, user: { id: string; name: string; email: string }) {
  let p = await prisma.chatParticipant.findFirst({ where: { projectId, userId: user.id } });
  p ??= await prisma.chatParticipant.findFirst({ where: { projectId, displayName: user.name } });
  if (p && !p.userId) p = await prisma.chatParticipant.update({ where: { id: p.id }, data: { userId: user.id } });
  p ??= await prisma.chatParticipant.create({ data: { projectId, displayName: user.name, email: user.email, userId: user.id } });
  return p;
}

export interface PostInput { room: { id: string; projectId: string | null }; user: { id: string; name: string; email: string }; text: string; replyToId?: string | null }

export async function postMessage(input: PostInput, queue?: JobQueue) {
  const { room, user } = input;
  const text = input.text.replace(/\r\n/g, '\n').trim().slice(0, MAX_TEXT);
  let replyToId: string | null = null;
  if (input.replyToId) {
    const target = await prisma.roomMessage.findFirst({ where: { id: input.replyToId, roomId: room.id }, select: { id: true } });   // a reply must stay inside the room
    replyToId = target?.id ?? null;
  }
  const msg = await prisma.roomMessage.create({ data: { roomId: room.id, senderId: user.id, text, replyToId } });

  if (room.projectId) {
    const pid = room.projectId;
    await serial(pid, async () => {
      const project = await prisma.project.findUnique({ where: { id: pid }, select: { timezone: true } });
      const [uploadId, part, last] = await Promise.all([carrierUpload(pid, user.id), participantFor(pid, user),
        prisma.chatMessage.aggregate({ where: { projectId: pid }, _max: { seq: true } })]);
      const mirrored = await prisma.chatMessage.create({ data: {
        id: mirroredId(pid, msg.id), projectId: pid, uploadId, seq: (last._max.seq ?? -1) + 1, senderId: part.id,
        timestamp: toWallClock(msg.createdAt, project?.timezone ?? 'Asia/Kolkata'), originalText: text, text, messageType: 'TEXT', isMedia: false,
        urls: text.match(/https?:\/\/\S+/g) ?? [], replyToId: replyToId ? mirroredId(pid, replyToId) : null } });
      await prisma.roomMessage.update({ where: { id: msg.id }, data: { chatMessageId: mirrored.id } });
    });
    if (queue) scheduleReanalysis(pid, queue);
  }
  await notifyRoom(room, 'chat.message');
  return msg;
}
