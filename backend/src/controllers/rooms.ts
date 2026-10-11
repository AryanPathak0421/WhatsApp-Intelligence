import { Router } from 'express';
import { z } from 'zod';
import { prisma } from '../db';
import { authenticate, requirePermission } from '../middlewares/auth';
import { audit, rateLimiter, validateBody } from '../middlewares/misc';
import { JobQueue } from '../queues';
import { AppError, asyncHandler, forbidden, notFound } from '../utils/errors';
import { isAdmin } from '../utils/permissions';
import { events } from '../events/bus';
import { MAX_TEXT, directKey, notifyRoom, postMessage } from '../services/rooms';
import { acceptInvite, createInvite, describeInvite, emailAddedMembers } from '../services/invites';
import { issueTokens, publicUser } from './auth';

const createBody = z.object({
  name: z.string().trim().min(1).max(80),
  projectId: z.string().uuid().optional(),
  memberIds: z.array(z.string().uuid()).max(100).default([]),
});
const directBody = z.object({ userId: z.string().uuid() });
const messageBody = z.object({ text: z.string().max(MAX_TEXT).refine((t) => t.trim().length > 0, 'Message is empty'), replyToId: z.string().uuid().optional() });
const memberBody = z.object({ userId: z.string().uuid() });
const renameBody = z.object({ name: z.string().trim().min(1).max(80) });
const inviteBody = z.object({ email: z.string().trim().toLowerCase().email().max(200), name: z.string().trim().max(100).optional() });
const acceptBody = z.object({ name: z.string().trim().min(1).max(100), password: z.string().min(10, 'Password must be at least 10 characters').max(200) });
const tokenOk = (t: string) => /^[A-Za-z0-9_-]{20,200}$/.test(t);

const sendLimit = rateLimiter(60, 60_000, (req) => `room:${req.user!.id}`);
const inviteLimit = rateLimiter(30, 60 * 60_000, (req) => `invite:${req.user!.id}`);        // e-mails cost reputation: 30 invitations per hour per person
const acceptLimit = rateLimiter(20, 15 * 60_000, (req) => `accept:${req.ip}`);
const lastTyping = new Map<string, number>();                                            // userId:roomId -> last broadcast (at most one per 2 s)
const actor = async (id: string) => (await prisma.user.findUnique({ where: { id }, select: { id: true, name: true } }))!;

/** In-app chat API. Every route needs a signed-in user; a room is visible only to its members (and only while they still have access to its project). */
export function roomsRouter(queue: JobQueue) {
  const r = Router();
  r.use('/rooms', authenticate);
  r.use('/room-users', authenticate);

  // a person may use a room only while they are a member AND (for project rooms) still allowed to see the project
  async function loadRoom(roomId: string, user: { id: string; role: any }) {
    const m = await prisma.roomMember.findUnique({ where: { roomId_userId: { roomId, userId: user.id } }, include: { room: true } });
    if (!m || m.room.archivedAt) throw notFound('Room');
    if (m.room.projectId && !isAdmin(user.role)) {
      const pm = await prisma.projectMember.findUnique({ where: { projectId_userId: { projectId: m.room.projectId, userId: user.id } } });
      if (!pm?.canView) throw notFound('Room');
    }
    return m;
  }
  const canManage = (room: { createdById: string }, user: { id: string; role: any }) => isAdmin(user.role) || room.createdById === user.id;

  async function assertCanAdd(room: { kind: string; projectId: string | null }, targetId: string) {
    const t = await prisma.user.findUnique({ where: { id: targetId }, select: { id: true, role: true, isActive: true } });
    if (!t || !t.isActive) throw new AppError(400, 'BAD_MEMBER', 'That user does not exist or is deactivated');
    if (room.projectId) {
      const ok = isAdmin(t.role) || Boolean(await prisma.projectMember.findFirst({ where: { projectId: room.projectId, userId: t.id, canView: true }, select: { id: true } }));
      if (!ok) throw new AppError(400, 'NOT_PROJECT_MEMBER', 'Only people who have access to the project can join its group');
    }
    return t;
  }

  // ---- directory for the "new chat / add people" pickers ----
  r.get('/room-users', asyncHandler(async (req, res) => {
    const user = req.user!;
    if (user.role === 'CLIENT_VIEWER') return void res.json({ items: [] });
    const projectId = typeof req.query.projectId === 'string' ? req.query.projectId : undefined;
    let where: any = { isActive: true, id: { not: user.id }, role: { not: 'CLIENT_VIEWER' } };
    if (projectId) {
      if (!isAdmin(user.role) && !(await prisma.projectMember.findFirst({ where: { projectId, userId: user.id, canView: true }, select: { id: true } }))) throw notFound('Project');
      where = { isActive: true, id: { not: user.id }, OR: [{ role: { in: ['ADMIN', 'SUPER_ADMIN'] } }, { memberships: { some: { projectId, canView: true } } }] };
    }
    const items = await prisma.user.findMany({ where, orderBy: { name: 'asc' }, take: 200, select: { id: true, name: true, role: true } });
    res.json({ items });
  }));

  // ---- my rooms, with last message and unread count ----
  r.get('/rooms', asyncHandler(async (req, res) => {
    const user = req.user!;
    const mine = await prisma.roomMember.findMany({ where: { userId: user.id, room: { archivedAt: null } }, include: { room: { include: { project: { select: { id: true, name: true } },
      members: { select: { userId: true, user: { select: { name: true } } } } } } } });
    const visible = [];
    for (const m of mine) {                                                                    // drop project rooms the user can no longer see
      if (m.room.projectId && !isAdmin(user.role) && !(await prisma.projectMember.findFirst({ where: { projectId: m.room.projectId, userId: user.id, canView: true }, select: { id: true } }))) continue;
      visible.push(m);
    }
    const items = await Promise.all(visible.map(async (m) => {
      const [last, unread] = await Promise.all([
        prisma.roomMessage.findFirst({ where: { roomId: m.roomId }, orderBy: { createdAt: 'desc' }, include: { sender: { select: { name: true } } } }),
        prisma.roomMessage.count({ where: { roomId: m.roomId, createdAt: { gt: m.lastReadAt }, senderId: { not: user.id } } })]);
      const other = m.room.kind === 'DIRECT' ? m.room.members.find((x) => x.userId !== user.id) : undefined;
      return { id: m.roomId, kind: m.room.kind, name: other?.user.name ?? m.room.name, project: m.room.project, memberCount: m.room.members.length, unread,
        lastMessage: last ? { text: last.text.slice(0, 140), senderName: last.sender.name, mine: last.senderId === user.id, at: last.createdAt } : null, lastActivity: last?.createdAt ?? m.room.createdAt };
    }));
    items.sort((a, b) => +new Date(b.lastActivity) - +new Date(a.lastActivity));
    res.json({ items, totalUnread: items.reduce((s, i) => s + i.unread, 0) });
  }));

  // ---- create a group (admin / project manager) ----
  r.post('/rooms', requirePermission('member:manage'), validateBody(createBody), asyncHandler(async (req, res) => {
    const user = req.user!, b = req.body as z.infer<typeof createBody>;
    if (b.projectId) {
      const p = await prisma.project.findUnique({ where: { id: b.projectId }, select: { id: true } });
      const pm = isAdmin(user.role) ? { canEdit: true } : await prisma.projectMember.findUnique({ where: { projectId_userId: { projectId: b.projectId, userId: user.id } } });
      if (!p || !pm) throw notFound('Project');
      if (!pm.canEdit) throw forbidden('Read-only access to this project');
    }
    const others = [...new Set(b.memberIds)].filter((id) => id !== user.id);
    for (const id of others) await assertCanAdd({ kind: 'GROUP', projectId: b.projectId ?? null }, id);
    const room = await prisma.chatRoom.create({ data: { kind: 'GROUP', name: b.name, projectId: b.projectId ?? null, createdById: user.id,
      members: { create: [user.id, ...others].map((userId) => ({ userId })) } } });
    await audit(req, 'CREATE_CHAT_GROUP', { entity: 'ChatRoom', entityId: room.id, projectId: b.projectId });
    await notifyRoom(room, 'chat.room');
    emailAddedMembers(room, others, await actor(user.id));
    res.status(201).json({ id: room.id, name: room.name, kind: room.kind, projectId: room.projectId });
  }));

  // ---- start (or reopen) a direct chat ----
  r.post('/rooms/direct', validateBody(directBody), asyncHandler(async (req, res) => {
    const user = req.user!, { userId } = req.body as z.infer<typeof directBody>;
    if (user.role === 'CLIENT_VIEWER') throw forbidden('Client accounts cannot start direct chats');
    if (userId === user.id) throw new AppError(400, 'BAD_MEMBER', 'You cannot chat with yourself');
    const t = await prisma.user.findUnique({ where: { id: userId }, select: { id: true, name: true, role: true, isActive: true } });
    if (!t || !t.isActive || t.role === 'CLIENT_VIEWER') throw new AppError(400, 'BAD_MEMBER', 'That user cannot receive direct chats');
    const key = directKey(user.id, userId);
    let room = await prisma.chatRoom.findUnique({ where: { directKey: key } });
    const created = !room;
    room ??= await prisma.chatRoom.create({ data: { kind: 'DIRECT', name: 'Direct chat', directKey: key, createdById: user.id, members: { create: [{ userId: user.id }, { userId }] } } });
    if (created) await notifyRoom(room, 'chat.room');
    res.status(created ? 201 : 200).json({ id: room.id, kind: room.kind });
  }));

  // ---- one room ----
  r.get('/rooms/:rid', asyncHandler(async (req, res) => {
    const user = req.user!;
    const m = await loadRoom(req.params.rid, user);
    const members = await prisma.roomMember.findMany({ where: { roomId: m.roomId }, include: { user: { select: { id: true, name: true, role: true } } }, orderBy: { joinedAt: 'asc' } });
    const project = m.room.projectId ? await prisma.project.findUnique({ where: { id: m.room.projectId }, select: { id: true, name: true } }) : null;
    const other = m.room.kind === 'DIRECT' ? members.find((x) => x.userId !== user.id) : undefined;
    res.json({ id: m.roomId, kind: m.room.kind, name: other?.user.name ?? m.room.name, project, canManage: canManage(m.room, user) && m.room.kind === 'GROUP',
      analysed: Boolean(m.room.projectId), members: members.map((x) => ({ id: x.user.id, name: x.user.name, role: x.user.role })) });
  }));

  r.patch('/rooms/:rid', validateBody(renameBody), asyncHandler(async (req, res) => {
    const m = await loadRoom(req.params.rid, req.user!);
    if (m.room.kind !== 'GROUP' || !canManage(m.room, req.user!)) throw forbidden();
    await prisma.chatRoom.update({ where: { id: m.roomId }, data: { name: (req.body as z.infer<typeof renameBody>).name } });
    await notifyRoom(m.room, 'chat.room');
    res.json({ ok: true });
  }));

  // ---- messages ----
  r.get('/rooms/:rid/messages', asyncHandler(async (req, res) => {
    const user = req.user!;
    const m = await loadRoom(req.params.rid, user);
    const limit = Math.min(Math.max(Number(req.query.limit) || 50, 1), 100);
    const before = typeof req.query.before === 'string' && !Number.isNaN(Date.parse(req.query.before)) ? new Date(req.query.before) : undefined;
    const rows = await prisma.roomMessage.findMany({ where: { roomId: m.roomId, ...(before ? { createdAt: { lt: before } } : {}) }, orderBy: { createdAt: 'desc' }, take: limit + 1,
      include: { sender: { select: { id: true, name: true } } } });
    const page = rows.slice(0, limit).reverse();
    const replyIds = [...new Set(page.map((x) => x.replyToId).filter(Boolean) as string[])];
    const replies = replyIds.length ? await prisma.roomMessage.findMany({ where: { id: { in: replyIds }, roomId: m.roomId }, include: { sender: { select: { name: true } } } }) : [];
    const rmap = new Map(replies.map((x) => [x.id, x]));
    // read ticks for my messages: 'read' once EVERY other member has opened the room after the message was sent, else 'sent'
    const others = await prisma.roomMember.findMany({ where: { roomId: m.roomId, userId: { not: user.id } }, select: { lastReadAt: true } });
    const statusOf = (at: Date) => (others.length > 0 && others.every((o) => o.lastReadAt >= at) ? 'read' : 'sent');
    res.json({ hasMore: rows.length > limit, items: page.map((x) => ({ id: x.id, senderId: x.sender.id, senderName: x.sender.name, mine: x.sender.id === user.id, text: x.text, createdAt: x.createdAt,
      status: x.sender.id === user.id ? statusOf(x.createdAt) : undefined,
      replyTo: x.replyToId && rmap.get(x.replyToId) ? { id: x.replyToId, senderName: rmap.get(x.replyToId)!.sender.name, text: rmap.get(x.replyToId)!.text.slice(0, 120) } : null })) });
  }));

  r.post('/rooms/:rid/messages', validateBody(messageBody), asyncHandler(async (req, res) => {
    const user = req.user!;
    if (!sendLimit.check(req)) throw new AppError(429, 'RATE_LIMITED', 'You are sending messages too quickly');
    sendLimit.fail(req);
    const m = await loadRoom(req.params.rid, user);
    const me = await prisma.user.findUnique({ where: { id: user.id }, select: { id: true, name: true, email: true } });
    const b = req.body as z.infer<typeof messageBody>;
    const msg = await postMessage({ room: m.room, user: me!, text: b.text, replyToId: b.replyToId }, queue);
    await prisma.roomMember.update({ where: { id: m.id }, data: { lastReadAt: msg.createdAt } });
    res.status(201).json({ id: msg.id, createdAt: msg.createdAt });
  }));

  // "typing..." indicator: ephemeral, never stored, sent to the OTHER members only
  r.post('/rooms/:rid/typing', asyncHandler(async (req, res) => {
    const user = req.user!;
    const m = await loadRoom(req.params.rid, user);
    const key = `${user.id}:${m.roomId}`;
    if (Date.now() - (lastTyping.get(key) ?? 0) >= 2000) {
      lastTyping.set(key, Date.now());
      const others = (await prisma.roomMember.findMany({ where: { roomId: m.roomId, userId: { not: user.id } }, select: { userId: true } })).map((x) => x.userId);
      events.publish({ type: 'chat.typing', projectId: m.room.projectId ?? '', roomId: m.roomId, userIds: others, actorId: user.id });
    }
    res.status(204).end();
  }));

  r.post('/rooms/:rid/read', asyncHandler(async (req, res) => {
    const m = await loadRoom(req.params.rid, req.user!);
    await prisma.roomMember.update({ where: { id: m.id }, data: { lastReadAt: new Date() } });
    await notifyRoom(m.room, 'chat.room');                                  // senders' ticks turn blue
    res.status(204).end();
  }));

  // ---- members ----
  r.post('/rooms/:rid/members', validateBody(memberBody), asyncHandler(async (req, res) => {
    const m = await loadRoom(req.params.rid, req.user!);
    if (m.room.kind !== 'GROUP' || !canManage(m.room, req.user!)) throw forbidden();
    const { userId } = req.body as z.infer<typeof memberBody>;
    await assertCanAdd(m.room, userId);
    const already = await prisma.roomMember.findUnique({ where: { roomId_userId: { roomId: m.roomId, userId } } });
    if (!already) await prisma.roomMember.create({ data: { roomId: m.roomId, userId } });
    await audit(req, 'ADD_CHAT_MEMBER', { entity: 'ChatRoom', entityId: m.roomId, projectId: m.room.projectId ?? undefined });
    await notifyRoom(m.room, 'chat.room');
    if (!already) emailAddedMembers(m.room, [userId], await actor(req.user!.id));
    res.status(204).end();
  }));

  r.delete('/rooms/:rid/members/:uid', asyncHandler(async (req, res) => {
    const user = req.user!;
    const m = await loadRoom(req.params.rid, user);
    if (m.room.kind !== 'GROUP') throw forbidden();
    if (req.params.uid !== user.id && !canManage(m.room, user)) throw forbidden();          // anyone may leave; only a manager removes others
    const room = m.room;
    const ids = await prisma.roomMember.findMany({ where: { roomId: room.id }, select: { userId: true } });
    await prisma.roomMember.deleteMany({ where: { roomId: room.id, userId: req.params.uid } });
    await audit(req, 'REMOVE_CHAT_MEMBER', { entity: 'ChatRoom', entityId: room.id, projectId: room.projectId ?? undefined });
    events.publish({ type: 'chat.room', projectId: room.projectId ?? '', roomId: room.id, userIds: ids.map((x) => x.userId) });   // includes the removed person, so their list refreshes
    res.status(204).end();
  }));

  // ---- e-mail invitations ----
  // existing account: added straight away (for a project group it must already have access to the project) + a notice e-mail; no account: an invitation link
  r.post('/rooms/:rid/invite', validateBody(inviteBody), asyncHandler(async (req, res) => {
    const user = req.user!;
    const m = await loadRoom(req.params.rid, user);
    if (m.room.kind !== 'GROUP' || !canManage(m.room, user)) throw forbidden();
    if (m.room.projectId && !isAdmin(user.role)) {                                        // the invitation grants project access, so the inviter needs edit rights
      const pm = await prisma.projectMember.findUnique({ where: { projectId_userId: { projectId: m.room.projectId, userId: user.id } } });
      if (!pm?.canEdit) throw forbidden('You need edit access to the project to invite people');
    }
    if (!inviteLimit.check(req)) throw new AppError(429, 'RATE_LIMITED', 'Too many invitations. Try again later.');
    inviteLimit.fail(req);
    const b = req.body as z.infer<typeof inviteBody>;
    const me = await actor(user.id);
    const existing = await prisma.user.findUnique({ where: { email: b.email }, select: { id: true } });
    if (existing) {
      await assertCanAdd(m.room, existing.id);
      const already = await prisma.roomMember.findUnique({ where: { roomId_userId: { roomId: m.roomId, userId: existing.id } } });
      if (!already) {
        await prisma.roomMember.create({ data: { roomId: m.roomId, userId: existing.id } });
        await notifyRoom(m.room, 'chat.room');
        emailAddedMembers(m.room, [existing.id], me);
      }
      await audit(req, 'ADD_CHAT_MEMBER', { entity: 'ChatRoom', entityId: m.roomId, projectId: m.room.projectId ?? undefined });
      return void res.status(200).json({ status: already ? 'already_member' : 'added' });
    }
    const inv = await createInvite(m.room, b.email, b.name, me);
    await audit(req, 'INVITE_TO_CHAT', { entity: 'ChatRoom', entityId: m.roomId, projectId: m.room.projectId ?? undefined });   // no e-mail address in the audit meta
    res.status(201).json({ status: 'invited', inviteId: inv.id, expiresAt: inv.expiresAt, emailSent: inv.emailSent });
  }));

  r.get('/rooms/:rid/invites', asyncHandler(async (req, res) => {
    const m = await loadRoom(req.params.rid, req.user!);
    if (!canManage(m.room, req.user!)) throw forbidden();
    const items = await prisma.chatInvite.findMany({ where: { roomId: m.roomId, acceptedAt: null, revokedAt: null, expiresAt: { gt: new Date() } }, orderBy: { createdAt: 'desc' },
      select: { id: true, email: true, name: true, expiresAt: true, createdAt: true } });
    res.json({ items });
  }));

  r.delete('/rooms/:rid/invites/:iid', asyncHandler(async (req, res) => {
    const m = await loadRoom(req.params.rid, req.user!);
    if (!canManage(m.room, req.user!)) throw forbidden();
    await prisma.chatInvite.updateMany({ where: { id: req.params.iid, roomId: m.roomId, acceptedAt: null }, data: { revokedAt: new Date() } });
    res.status(204).end();
  }));

  // public: the person who received the e-mail has no account yet
  r.get('/invites/:token', asyncHandler(async (req, res) => {
    if (!tokenOk(req.params.token)) throw new AppError(404, 'INVITE_NOT_FOUND', 'This invitation is not valid');
    res.json(await describeInvite(req.params.token));
  }));

  r.post('/invites/:token/accept', validateBody(acceptBody), asyncHandler(async (req, res) => {
    if (!acceptLimit.check(req)) throw new AppError(429, 'TOO_MANY_ATTEMPTS', 'Too many attempts. Try again later.');
    acceptLimit.fail(req);
    if (!tokenOk(req.params.token)) throw new AppError(404, 'INVITE_NOT_FOUND', 'This invitation is not valid');
    const b = req.body as z.infer<typeof acceptBody>;
    const { user, roomId } = await acceptInvite(req.params.token, b.name, b.password);
    res.status(201).json({ user: publicUser(user), roomId, ...(await issueTokens(user, req)) });
  }));

  return r;
}
