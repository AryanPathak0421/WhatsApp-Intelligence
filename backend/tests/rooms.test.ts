import request from 'supertest';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { prisma } from '../src/db';
import { events, LiveEvent } from '../src/events/bus';
import { eraseProjectData } from '../src/services/retention';
import { _timersForTests } from '../src/services/reanalysis';
import { bootstrapAdmin, createUser, makeCtx, resetDb, Session } from './helpers';

const ctx = makeCtx();
let admin: Session, pm: Session, dev: Session, dev2: Session, outsider: Session, client: Session;
let pid: string, room: string;
const seen: LiveEvent[] = [];
let off = () => undefined as void;

const api = (s: Session) => ({
  get: (u: string) => request(ctx.app).get('/api' + u).set(s.auth),
  post: (u: string, b?: object) => request(ctx.app).post('/api' + u).set(s.auth).send(b ?? {}),
  del: (u: string) => request(ctx.app).delete('/api' + u).set(s.auth),
});

beforeAll(async () => {
  await resetDb();
  admin = await bootstrapAdmin(ctx);
  pm = await createUser(ctx, admin, 'PROJECT_MANAGER', 'pm@example.com');
  dev = await createUser(ctx, admin, 'TEAM_MEMBER', 'dev@example.com');
  dev2 = await createUser(ctx, admin, 'TEAM_MEMBER', 'dev2@example.com');
  outsider = await createUser(ctx, admin, 'TEAM_MEMBER', 'out@example.com');
  client = await createUser(ctx, admin, 'CLIENT_VIEWER', 'client@example.com');
  pid = (await api(pm).post('/projects', { name: 'In-app chat project' })).body.id;
  for (const u of [dev, dev2, client]) await api(pm).post(`/projects/${pid}/members`, { userId: u.user.id });
  off = events.subscribe((e) => { if (e.type.startsWith('chat.')) seen.push(e); }) as unknown as () => void;
});
afterAll(async () => { off(); for (const t of _timersForTests.values()) clearTimeout(t.timer); _timersForTests.clear(); await ctx.queue.close(); await prisma.$disconnect(); });

describe('creating groups', () => {
  it('only admin / project manager with edit access can create a group; members must belong to the project', async () => {
    expect((await api(dev).post('/rooms', { name: 'x', projectId: pid })).status).toBe(403);
    expect((await api(outsider).post('/rooms', { name: 'x', projectId: pid })).status).toBe(403);
    const otherPm = await createUser(ctx, admin, 'PROJECT_MANAGER', 'pm2@example.com');
    expect((await api(otherPm).post('/rooms', { name: 'x', projectId: pid })).status).toBe(404);              // not on this project: existence is not leaked
    const bad = await api(pm).post('/rooms', { name: 'Sprint', projectId: pid, memberIds: [outsider.user.id] });
    expect(bad.status).toBe(400);
    const ok = await api(pm).post('/rooms', { name: 'Sprint', projectId: pid, memberIds: [dev.user.id, dev2.user.id, client.user.id] });
    expect(ok.status).toBe(201);
    room = ok.body.id;
    expect((await api(pm).get(`/rooms/${room}`)).body.members).toHaveLength(4);
    expect((await api(pm).get(`/rooms/${room}`)).body.analysed).toBe(true);
  });
  it('a group without a project can be created with team members', async () => {
    expect((await api(pm).post('/rooms', { name: 'Team lunch', memberIds: [dev.user.id] })).status).toBe(201);
  });
});

describe('messages in a project group', () => {
  it('delivers to members, hides the room from everyone else, and rejects empty text', async () => {
    const r = await api(dev).post(`/rooms/${room}/messages`, { text: 'Priya, please finish the login page by Friday' });
    expect(r.status).toBe(201);
    const list = await api(dev2).get(`/rooms/${room}/messages`);
    expect(list.body.items).toHaveLength(1);
    expect(list.body.items[0]).toMatchObject({ text: 'Priya, please finish the login page by Friday', mine: false });
    expect(list.body.items[0].senderName).toBeTruthy();
    expect((await api(outsider).get(`/rooms/${room}/messages`)).status).toBe(404);
    expect((await api(outsider).post(`/rooms/${room}/messages`, { text: 'hi' })).status).toBe(404);
    expect((await api(dev).post(`/rooms/${room}/messages`, { text: '   ' })).status).toBe(422);
  });
  it('mirrors the message into the project chat (so analysis covers it) and schedules one debounced re-analysis', async () => {
    const mirrored = await prisma.chatMessage.findMany({ where: { projectId: pid }, include: { sender: true } });
    expect(mirrored).toHaveLength(1);
    expect(mirrored[0]).toMatchObject({ text: 'Priya, please finish the login page by Friday', originalText: 'Priya, please finish the login page by Friday', messageType: 'TEXT' });
    expect(mirrored[0].sender?.userId).toBe(dev.user.id);
    expect(_timersForTests.has(pid)).toBe(true);
    await api(dev2).post(`/rooms/${room}/messages`, { text: 'On it, build tonight' });
    expect(await prisma.chatMessage.count({ where: { projectId: pid } })).toBe(2);
    const seqs = (await prisma.chatMessage.findMany({ where: { projectId: pid }, orderBy: { seq: 'asc' } })).map((m) => m.seq);
    expect(seqs).toEqual([0, 1]);
  });
  it('a reply keeps the quoted text, and cannot point at a message of another room', async () => {
    const first = (await api(dev).get(`/rooms/${room}/messages`)).body.items[0];
    await api(dev2).post(`/rooms/${room}/messages`, { text: 'ack', replyToId: first.id });
    const last = (await api(dev).get(`/rooms/${room}/messages`)).body.items.at(-1);
    expect(last.replyTo).toMatchObject({ id: first.id });
    const other = (await api(pm).post('/rooms', { name: 'Other', projectId: pid, memberIds: [dev.user.id] })).body.id;
    const foreign = (await api(dev).post(`/rooms/${other}/messages`, { text: 'in another room' })).body;
    await api(dev2).post(`/rooms/${room}/messages`, { text: 'sneaky', replyToId: foreign.id });
    expect((await api(dev).get(`/rooms/${room}/messages`)).body.items.at(-1).replyTo).toBeNull();
  });
  it('tracks unread counts per person and clears them on read', async () => {
    const before = (await api(pm).get('/rooms')).body;
    const mine = before.items.find((i: any) => i.id === room);
    expect(mine.unread).toBeGreaterThanOrEqual(3);
    expect(mine.lastMessage.text).toBeTruthy();
    expect((await api(pm).post(`/rooms/${room}/read`)).status).toBe(204);
    expect((await api(pm).get('/rooms')).body.items.find((i: any) => i.id === room).unread).toBe(0);
    expect((await api(dev).get('/rooms')).body.items.find((i: any) => i.id === room).unread).toBeGreaterThan(0);   // someone else's messages are still unread for dev
  });
  it('shows sent / read ticks on my messages: read only once every other member has opened the room', async () => {
    const mineAt = async (s: Session) => (await api(s).get(`/rooms/${room}/messages`)).body.items.filter((x: any) => x.mine);
    const sent = await api(pm).post(`/rooms/${room}/messages`, { text: 'Status check please' });
    expect(sent.status).toBe(201);
    expect((await mineAt(pm)).at(-1).status).toBe('sent');
    expect((await mineAt(pm)).at(-1)).toHaveProperty('status');
    expect((await api(dev).get(`/rooms/${room}/messages`)).body.items.every((x: any) => x.status === undefined || x.mine)).toBe(true);   // status only on my own
    await api(dev).post(`/rooms/${room}/read`);
    expect((await mineAt(pm)).at(-1).status).toBe('sent');                  // dev2 and the client have not read it yet
    await api(dev2).post(`/rooms/${room}/read`);
    await api(client).post(`/rooms/${room}/read`);
    expect((await mineAt(pm)).at(-1).status).toBe('read');
  });
  it('typing goes to the other members only, is throttled, and is refused to non-members', async () => {
    const before = seen.filter((e) => e.type === 'chat.typing').length;
    expect((await api(dev2).post(`/rooms/${room}/typing`)).status).toBe(204);
    expect((await api(dev2).post(`/rooms/${room}/typing`)).status).toBe(204);
    const typing = seen.filter((e) => e.type === 'chat.typing').slice(before);
    expect(typing).toHaveLength(1);
    expect(typing[0].actorId).toBe(dev2.user.id);
    expect(typing[0].userIds).not.toContain(dev2.user.id);
    expect(typing[0].userIds).toContain(dev.user.id);
    expect((await api(outsider).post(`/rooms/${room}/typing`)).status).toBe(404);
  });
  it('live events carry ids and the member list only, never message text', () => {
    const msgEvents = seen.filter((e) => e.type === 'chat.message' && e.roomId === room);
    expect(msgEvents.length).toBeGreaterThan(0);
    for (const e of msgEvents) {
      expect(e.userIds).toContain(dev.user.id);
      expect(e.userIds).not.toContain(outsider.user.id);
      expect(JSON.stringify(e)).not.toContain('login page');
    }
  });
});

describe('membership and access changes', () => {
  it('only the creator or an admin manages members; anyone can leave; a removed person loses access', async () => {
    expect((await api(dev).post(`/rooms/${room}/members`, { userId: outsider.user.id })).status).toBe(403);
    expect((await api(pm).post(`/rooms/${room}/members`, { userId: outsider.user.id })).status).toBe(400);     // not a project member
    expect((await api(dev).del(`/rooms/${room}/members/${dev2.user.id}`)).status).toBe(403);
    expect((await api(pm).del(`/rooms/${room}/members/${dev2.user.id}`)).status).toBe(204);
    expect((await api(dev2).get(`/rooms/${room}/messages`)).status).toBe(404);
    expect((await api(dev).del(`/rooms/${room}/members/${dev.user.id}`)).status).toBe(204);                  // leaving
    expect((await api(dev).get(`/rooms/${room}`)).status).toBe(404);
  });
  it('losing access to the project hides its groups even while still a room member', async () => {
    expect((await api(client).get(`/rooms/${room}`)).status).toBe(200);
    await prisma.projectMember.deleteMany({ where: { projectId: pid, userId: client.user.id } });
    expect((await api(client).get(`/rooms/${room}`)).status).toBe(404);
    expect((await api(client).get('/rooms')).body.items.find((i: any) => i.id === room)).toBeUndefined();
  });
});

describe('direct messages', () => {
  it('is one private room per pair, never mirrored into a project, and invisible to others', async () => {
    const a = await api(dev).post('/rooms/direct', { userId: dev2.user.id });
    expect(a.status).toBe(201);
    const b = await api(dev2).post('/rooms/direct', { userId: dev.user.id });
    expect(b.status).toBe(200);
    expect(b.body.id).toBe(a.body.id);
    const before = await prisma.chatMessage.count();
    expect((await api(dev).post(`/rooms/${a.body.id}/messages`, { text: 'private note' })).status).toBe(201);
    expect(await prisma.chatMessage.count()).toBe(before);
    expect((await api(dev2).get(`/rooms/${a.body.id}/messages`)).body.items[0].text).toBe('private note');
    expect((await api(outsider).get(`/rooms/${a.body.id}/messages`)).status).toBe(404);
    expect((await api(admin).get(`/rooms/${a.body.id}/messages`)).status).toBe(404);                       // even admins are not in someone else's DM
    expect((await api(dev).get('/rooms')).body.items.find((i: any) => i.id === a.body.id).name).toBe((await prisma.user.findUnique({ where: { id: dev2.user.id } }))!.name);   // a DM is titled with the other person
    expect((await api(client).post('/rooms/direct', { userId: dev.user.id })).status).toBe(403);
    expect((await api(dev).post('/rooms/direct', { userId: client.user.id })).status).toBe(400);
    expect((await api(dev).post('/rooms/direct', { userId: dev.user.id })).status).toBe(400);
  });
  it('requires sign-in and lists only people the caller may talk to', async () => {
    expect((await request(ctx.app).get('/api/rooms')).status).toBe(401);
    const users = (await api(dev).get('/room-users')).body.items.map((u: any) => u.id);
    expect(users).not.toContain(dev.user.id);
    expect(users).not.toContain(client.user.id);
    expect((await api(client).get('/room-users')).body.items).toEqual([]);
  });
});

describe('retention', () => {
  it('purging a project deletes its in-app messages too', async () => {
    await eraseProjectData(pid);
    expect(await prisma.roomMessage.count({ where: { room: { projectId: pid } } })).toBe(0);
    expect(await prisma.chatMessage.count({ where: { projectId: pid } })).toBe(0);
  });
});
