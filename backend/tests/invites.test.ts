import nodemailer from 'nodemailer';
import request from 'supertest';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { prisma } from '../src/db';
import { _setTransportForTests, sentForTests } from '../src/services/mailer';
import { _timersForTests } from '../src/services/reanalysis';
import { bootstrapAdmin, createUser, makeCtx, resetDb, Session } from './helpers';

const ctx = makeCtx();
let admin: Session, pm: Session, dev: Session, outsider: Session;
let pid: string, room: string;
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const api = (s: Session) => ({
  get: (u: string) => request(ctx.app).get('/api' + u).set(s.auth),
  post: (u: string, b?: object) => request(ctx.app).post('/api' + u).set(s.auth).send(b ?? {}),
  del: (u: string) => request(ctx.app).delete('/api' + u).set(s.auth),
});
const tokenFrom = (text: string) => /\/invite\/([A-Za-z0-9_-]+)/.exec(text)![1];

beforeAll(async () => {
  await resetDb();
  _setTransportForTests(nodemailer.createTransport({ jsonTransport: true }));              // nothing leaves the machine
  admin = await bootstrapAdmin(ctx);
  pm = await createUser(ctx, admin, 'PROJECT_MANAGER', 'pm@example.com');
  dev = await createUser(ctx, admin, 'TEAM_MEMBER', 'dev@example.com');
  outsider = await createUser(ctx, admin, 'TEAM_MEMBER', 'out@example.com');
  pid = (await api(pm).post('/projects', { name: 'Client portal <b>v2</b>' })).body.id;
  await api(pm).post(`/projects/${pid}/members`, { userId: dev.user.id });
  room = (await api(pm).post('/rooms', { name: 'Client <script>x</script> group', projectId: pid })).body.id;
});
afterAll(async () => { _setTransportForTests(null); for (const t of _timersForTests.values()) clearTimeout(t.timer); _timersForTests.clear(); await ctx.queue.close(); await prisma.$disconnect(); });

describe('inviting a client without an account', () => {
  let token = '';
  it('creates a single-use invitation and e-mails a link (names are HTML-escaped)', async () => {
    sentForTests.length = 0;
    const r = await api(pm).post(`/rooms/${room}/invite`, { email: 'Client@Acme.test', name: 'Meera' });
    expect(r.status).toBe(201);
    expect(r.body).toMatchObject({ status: 'invited', emailSent: true });
    expect(sentForTests).toHaveLength(1);
    const mail = sentForTests[0];
    expect(mail.to).toBe('client@acme.test');
    expect(mail.subject).toContain('invited you');
    expect(mail.html).not.toContain('<script>');
    expect(mail.html).toContain('&lt;script&gt;');
    token = tokenFrom(mail.text);
    const stored = await prisma.chatInvite.findFirst({ where: { email: 'client@acme.test' } });
    expect(stored!.tokenHash).not.toBe(token);                                           // only the hash is stored
    expect(JSON.stringify(await prisma.auditLog.findMany({ where: { action: 'INVITE_TO_CHAT' } }))).not.toContain('acme');
  });
  it('the public page describes the invitation without signing in', async () => {
    const d = await request(ctx.app).get(`/api/invites/${token}`);
    expect(d.status).toBe(200);
    expect(d.body).toMatchObject({ email: 'client@acme.test', name: 'Meera', projectName: 'Client portal <b>v2</b>', accountExists: false });
    expect((await request(ctx.app).get('/api/invites/not-a-real-token-123456789')).status).toBe(404);
    expect((await request(ctx.app).get('/api/invites/bad!')).status).toBe(404);
  });
  it('accepting creates a client account with view access to the project and membership of the group; the link then stops working', async () => {
    expect((await request(ctx.app).post(`/api/invites/${token}/accept`).send({ name: 'Meera', password: 'short' })).status).toBe(422);
    const ok = await request(ctx.app).post(`/api/invites/${token}/accept`).send({ name: 'Meera', password: 'a-long-enough-password' });
    expect(ok.status).toBe(201);
    expect(ok.body.user).toMatchObject({ email: 'client@acme.test', role: 'CLIENT_VIEWER' });
    expect(ok.body.roomId).toBe(room);
    const auth = { Authorization: `Bearer ${ok.body.accessToken}` };
    expect((await request(ctx.app).get(`/api/rooms/${room}/messages`).set(auth)).status).toBe(200);
    expect((await request(ctx.app).post(`/api/rooms/${room}/messages`).set(auth).send({ text: 'Hello team' })).status).toBe(201);
    const pmRow = await prisma.projectMember.findFirst({ where: { projectId: pid, user: { email: 'client@acme.test' } } });
    expect(pmRow).toMatchObject({ canView: true, canEdit: false });
    expect((await request(ctx.app).post(`/api/invites/${token}/accept`).send({ name: 'X', password: 'a-long-enough-password' })).status).toBe(410);
    expect((await request(ctx.app).get(`/api/invites/${token}`)).status).toBe(410);
  });
  it('a newer invitation replaces the older link, and revoked or expired links do not work', async () => {
    sentForTests.length = 0;
    await api(pm).post(`/rooms/${room}/invite`, { email: 'second@acme.test' });
    await api(pm).post(`/rooms/${room}/invite`, { email: 'second@acme.test' });
    const [first, second] = sentForTests.map((m) => tokenFrom(m.text));
    expect((await request(ctx.app).get(`/api/invites/${first}`)).status).toBe(404);
    expect((await request(ctx.app).get(`/api/invites/${second}`)).status).toBe(200);
    const pending = (await api(pm).get(`/rooms/${room}/invites`)).body.items;
    expect(pending).toHaveLength(1);
    await api(pm).del(`/rooms/${room}/invites/${pending[0].id}`);
    expect((await request(ctx.app).get(`/api/invites/${second}`)).status).toBe(404);
    sentForTests.length = 0;
    await api(pm).post(`/rooms/${room}/invite`, { email: 'late@acme.test' });
    await prisma.chatInvite.updateMany({ where: { email: 'late@acme.test' }, data: { expiresAt: new Date(Date.now() - 1000) } });
    expect((await request(ctx.app).get(`/api/invites/${tokenFrom(sentForTests[0].text)}`)).status).toBe(410);
  });
});

describe('who may invite, and existing accounts', () => {
  it('only the group manager with project edit access can invite', async () => {
    expect((await api(dev).post(`/rooms/${room}/invite`, { email: 'x@acme.test' })).status).toBe(404);     // not a member of the room
    const plain = (await api(pm).post('/rooms', { name: 'Internal', memberIds: [dev.user.id] })).body.id;
    expect((await api(dev).post(`/rooms/${plain}/invite`, { email: 'x@acme.test' })).status).toBe(403);
    expect((await api(pm).post(`/rooms/${room}/invite`, { email: 'not-an-email' })).status).toBe(422);
  });
  it('an existing account with project access is added at once and gets a notice; without access it is refused', async () => {
    sentForTests.length = 0;
    const r = await api(pm).post(`/rooms/${room}/invite`, { email: 'dev@example.com' });
    expect(r.body.status).toBe('added');
    await wait(200);
    expect(sentForTests.map((m) => m.to)).toEqual(['dev@example.com']);
    expect(sentForTests[0].text).toContain(`/chat/${room}`);
    expect((await api(pm).post(`/rooms/${room}/invite`, { email: 'dev@example.com' })).body.status).toBe('already_member');
    expect((await api(pm).post(`/rooms/${room}/invite`, { email: 'out@example.com' })).status).toBe(400);
  });
  it('adding people when creating a group or through "add member" e-mails them, never the person who added them', async () => {
    sentForTests.length = 0;
    const g = await api(pm).post('/rooms', { name: 'Release', projectId: pid, memberIds: [dev.user.id] });
    await wait(200);
    expect(sentForTests.map((m) => m.to)).toEqual(['dev@example.com']);
    sentForTests.length = 0;
    const other = await createUser(ctx, admin, 'TEAM_MEMBER', 'qa@example.com');
    await api(pm).post(`/projects/${pid}/members`, { userId: other.user.id });
    await api(pm).post(`/rooms/${g.body.id}/members`, { userId: other.user.id });
    await wait(200);
    expect(sentForTests.map((m) => m.to)).toEqual(['qa@example.com']);
  });
  it('without SMTP the invitation is still created and the response says the e-mail was not sent', async () => {
    _setTransportForTests(null);
    const r = await api(pm).post(`/rooms/${room}/invite`, { email: 'nosmtp@acme.test' });
    expect(r.status).toBe(201);
    expect(r.body.emailSent).toBe(false);
    _setTransportForTests(nodemailer.createTransport({ jsonTransport: true }));
  });
});

describe('inviting into a group without a project', () => {
  it('creates a client account that can use only that group, with no project access', async () => {
    sentForTests.length = 0;
    const plain = (await api(pm).post('/rooms', { name: 'Vendors' })).body.id;
    const r = await api(pm).post(`/rooms/${plain}/invite`, { email: 'vendor@acme.test', name: 'Vik' });
    expect(r.status).toBe(201);
    const ok = await request(ctx.app).post(`/api/invites/${tokenFrom(sentForTests[0].text)}/accept`).send({ name: 'Vik', password: 'a-long-enough-password' });
    expect(ok.status).toBe(201);
    const auth = { Authorization: `Bearer ${ok.body.accessToken}` };
    expect((await request(ctx.app).post(`/api/rooms/${plain}/messages`).set(auth).send({ text: 'hi' })).status).toBe(201);
    expect(await prisma.projectMember.count({ where: { user: { email: 'vendor@acme.test' } } })).toBe(0);
    expect((await request(ctx.app).get('/api/projects').set(auth)).body.items).toHaveLength(0);
    expect((await request(ctx.app).get(`/api/rooms/${room}`).set(auth)).status).toBe(404);
  });
});
