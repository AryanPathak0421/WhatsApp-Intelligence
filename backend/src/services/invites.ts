/**
 * Chat invitations by e-mail.
 *  - A person who already has an account and is added to a group gets a notice with a link to the chat.
 *  - A person without an account (typically a client) gets an invitation link. Accepting it creates a CLIENT_VIEWER account and joins the group;
 *    for a project group it also gets VIEW access to that project, for a group without a project it sees only that group. Tokens are single-use, expire (INVITE_TTL_DAYS), and only their hash is stored.
 */
import bcrypt from 'bcryptjs';
import { config } from '../config';
import { prisma } from '../db';
import { randomToken, sha256 } from '../utils/crypto';
import { AppError } from '../utils/errors';
import { escapeHtml, layout, sendMail } from './mailer';
import { notifyRoom } from './rooms';

type Room = { id: string; name: string; projectId: string | null };

async function projectName(projectId: string | null) {
  return projectId ? (await prisma.project.findUnique({ where: { id: projectId }, select: { name: true } }))?.name ?? null : null;
}

/** "X added you to <group>" to each added person (never to the person who did it). Best effort: never blocks or fails the request. */
export function emailAddedMembers(room: Room, userIds: string[], inviter: { id: string; name: string }): void {
  void (async () => {
    const people = await prisma.user.findMany({ where: { id: { in: userIds.filter((u) => u !== inviter.id) }, isActive: true }, select: { email: true, name: true } });
    const pname = await projectName(room.projectId);
    const url = `${config().FRONTEND_URL}/chat/${room.id}`;
    for (const p of people) {
      const subject = `${inviter.name} added you to "${room.name}"`;
      const text = `Hi ${p.name},\n\n${inviter.name} added you to the group "${room.name}"${pname ? ` (project ${pname})` : ''} on Project Intelligence.\n\nOpen the chat: ${url}\n`;
      const html = layout('You were added to a group', `<p>Hi ${escapeHtml(p.name)},</p><p><b>${escapeHtml(inviter.name)}</b> added you to the group <b>${escapeHtml(room.name)}</b>${pname ? ` (project ${escapeHtml(pname)})` : ''}.</p>`,
        { label: 'Open chat', url });
      await sendMail(p.email, subject, text, html);
    }
  })().catch((e) => console.error('[mail] added-member notice failed:', (e as Error).message));
}

export async function createInvite(room: Room, email: string, name: string | undefined, inviter: { id: string; name: string }) {
  const now = new Date();
  await prisma.chatInvite.updateMany({ where: { roomId: room.id, email, acceptedAt: null, revokedAt: null }, data: { revokedAt: now } });   // a new invite replaces the old link
  const token = randomToken();
  const expiresAt = new Date(now.getTime() + config().INVITE_TTL_DAYS * 86_400_000);
  const inv = await prisma.chatInvite.create({ data: { tokenHash: sha256(token), email, name: name || null, roomId: room.id, invitedById: inviter.id, expiresAt } });
  const pname = await projectName(room.projectId);
  const url = `${config().FRONTEND_URL}/invite/${token}`;
  const hello = name ? `Hi ${name},` : 'Hello,';
  const subject = `${inviter.name} invited you to join "${room.name}"`;
  const text = `${hello}\n\n${inviter.name} invited you to the group "${room.name}"${pname ? ` for the project ${pname}` : ''} on Project Intelligence.\n\nAccept the invitation and set your password: ${url}\n\nThe link works once and expires on ${expiresAt.toDateString()}.\n`;
  const html = layout('Invitation to a project group',
    `<p>${escapeHtml(hello)}</p><p><b>${escapeHtml(inviter.name)}</b> invited you to the group <b>${escapeHtml(room.name)}</b>${pname ? ` for the project <b>${escapeHtml(pname)}</b>` : ''}.</p>
<p>Accept the invitation to create your account and start chatting with the team.</p><p style="font-size:13px;color:#667781">The link works once and expires on ${escapeHtml(expiresAt.toDateString())}.</p>`,
    { label: 'Accept invitation', url });
  const emailSent = await sendMail(email, subject, text, html);
  return { id: inv.id, expiresAt, emailSent };
}

async function validInvite(token: string) {
  const inv = await prisma.chatInvite.findUnique({ where: { tokenHash: sha256(token) }, include: { room: true } });
  if (!inv || inv.revokedAt || inv.room.archivedAt) throw new AppError(404, 'INVITE_NOT_FOUND', 'This invitation is not valid');
  if (inv.acceptedAt) throw new AppError(410, 'INVITE_USED', 'This invitation was already used. Please sign in.');
  if (inv.expiresAt < new Date()) throw new AppError(410, 'INVITE_EXPIRED', 'This invitation has expired. Ask for a new one.');
  return inv;
}

export async function describeInvite(token: string) {
  const inv = await validInvite(token);
  const inviter = await prisma.user.findUnique({ where: { id: inv.invitedById }, select: { name: true } });
  return { email: inv.email, name: inv.name, roomName: inv.room.name, projectName: await projectName(inv.room.projectId), inviterName: inviter?.name ?? 'A team member',
    expiresAt: inv.expiresAt, accountExists: Boolean(await prisma.user.findUnique({ where: { email: inv.email }, select: { id: true } })) };
}

export async function acceptInvite(token: string, name: string, password: string) {
  const inv = await validInvite(token);
  if (await prisma.user.findUnique({ where: { email: inv.email }, select: { id: true } })) {
    throw new AppError(409, 'ACCOUNT_EXISTS', 'An account with this e-mail already exists. Sign in, and ask the group admin to add you.');
  }
  const projectId = inv.room.projectId;
  const passwordHash = await bcrypt.hash(password, 12);
  const user = await prisma.$transaction(async (tx) => {
    const claimed = await tx.chatInvite.updateMany({ where: { id: inv.id, acceptedAt: null, revokedAt: null }, data: { acceptedAt: new Date() } });   // single use, also under a race
    if (claimed.count !== 1) throw new AppError(410, 'INVITE_USED', 'This invitation was already used. Please sign in.');
    const u = await tx.user.create({ data: { email: inv.email, name, role: 'CLIENT_VIEWER', passwordHash } });
    if (projectId) await tx.projectMember.upsert({ where: { projectId_userId: { projectId, userId: u.id } }, update: { canView: true }, create: { projectId, userId: u.id, canView: true, canEdit: false } });
    await tx.roomMember.create({ data: { roomId: inv.roomId, userId: u.id } });
    await tx.auditLog.create({ data: { userId: u.id, action: 'ACCEPT_CHAT_INVITE', entity: 'ChatRoom', entityId: inv.roomId, projectId: projectId ?? undefined } });
    return u;
  });
  await notifyRoom(inv.room, 'chat.room');
  return { user, roomId: inv.roomId };
}
