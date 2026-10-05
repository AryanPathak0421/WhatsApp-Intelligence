import crypto from 'node:crypto';
import request from 'supertest';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { prisma } from '../src/db';
import { normalizeCloudPayload, toWallClock } from '../src/services/whatsapp';
import { bootstrapAdmin, createUser, makeCtx, resetDb, Session } from './helpers';

const SECRET = 'test-whatsapp-app-secret-0123456789';
const PHONE = '1098765432101';
const GROUP = 'GRP-abc123';
const ctx = makeCtx();
let admin: Session, pm: Session, member: Session, outsider: Session;
let pid: string;

const sign = (raw: string) => 'sha256=' + crypto.createHmac('sha256', SECRET).update(raw).digest('hex');
const t0 = Math.floor(Date.UTC(2026, 9, 1, 4, 30, 0) / 1000);        // 2026-10-01 04:30 UTC = 10:00 in Asia/Kolkata

function payload(messages: any[], contacts: any[] = [{ wa_id: '919800000001', profile: { name: 'Priya' } }, { wa_id: '919800000002', profile: { name: 'Rahul' } }], phone = PHONE) {
  return { object: 'whatsapp_business_account', entry: [{ id: 'WABA', changes: [{ field: 'messages', value: { messaging_product: 'whatsapp', metadata: { phone_number_id: phone }, contacts, messages } }] }] };
}
const post = (body: unknown, sig?: string) => {
  const raw = JSON.stringify(body);
  return request(ctx.app).post('/api/webhooks/whatsapp').set('Content-Type', 'application/json').set('X-Hub-Signature-256', sig ?? sign(raw)).send(raw);
};
const gm = (id: string, from: string, text: string, ts = t0, extra: object = {}) => ({ id, from, timestamp: String(ts), type: 'text', text: { body: text }, group_id: GROUP, ...extra });
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

beforeAll(async () => {
  await resetDb();
  admin = await bootstrapAdmin(ctx);
  pm = await createUser(ctx, admin, 'PROJECT_MANAGER', 'pm@example.com');
  member = await createUser(ctx, admin, 'TEAM_MEMBER', 'member@example.com');
  outsider = await createUser(ctx, admin, 'PROJECT_MANAGER', 'other@example.com');
  pid = (await request(ctx.app).post('/api/projects').set(pm.auth).send({ name: 'Live ingestion' })).body.id;
  await request(ctx.app).post(`/api/projects/${pid}/members`).set(pm.auth).send({ userId: member.user.id });
});
afterAll(async () => { await wait(400); await ctx.queue.close(); await prisma.$disconnect(); });

describe('normalisation (pure)', () => {
  it('maps text, media, reply and reaction, and skips status updates and malformed entries', () => {
    const body = payload([gm('m1', '919800000001', 'hello'), { id: 'm2', from: '919800000002', timestamp: String(t0), type: 'image', image: { mime_type: 'image/jpeg', caption: 'logo' }, group_id: GROUP },
      gm('m3', '919800000002', 'reply', t0, { context: { id: 'm1' } }), { id: 'm4', from: '919800000001', timestamp: String(t0), type: 'reaction', reaction: { message_id: 'm1', emoji: '👍' }, group_id: GROUP },
      { id: 'bad' }, { id: 'm5', from: 'x', timestamp: 'not-a-number', type: 'text', text: { body: 'x' } }]);
    (body.entry[0].changes[0].value as any).statuses = [{ id: 's1', status: 'delivered' }];
    const u = normalizeCloudPayload(body);
    expect(u.map((m) => m.messageType)).toEqual(['text', 'image', 'text', 'reaction']);
    expect(u[0]).toMatchObject({ isGroup: true, conversationId: GROUP, senderName: 'Priya' });
    expect(u[1]).toMatchObject({ text: '<Media omitted>\nlogo', media: { kind: 'image', caption: 'logo' } });
    expect(u[2].replyTo).toBe('m1');
    expect(normalizeCloudPayload({})).toEqual([]);
    expect(normalizeCloudPayload(null)).toEqual([]);
  });
  it('converts a UTC instant to the project wall clock', () => {
    expect(toWallClock(new Date(Date.UTC(2026, 9, 1, 4, 30)), 'Asia/Kolkata').toISOString()).toBe('2026-10-01T10:00:00.000Z');
    expect(toWallClock(new Date(Date.UTC(2026, 9, 1, 18, 45)), 'Asia/Kolkata').toISOString()).toBe('2026-10-02T00:15:00.000Z');
  });
});

describe('verification handshake and signatures', () => {
  it('echoes the challenge only for the right token', async () => {
    const ok = await request(ctx.app).get('/api/webhooks/whatsapp').query({ 'hub.mode': 'subscribe', 'hub.verify_token': 'verify-token-12345', 'hub.challenge': '777' });
    expect(ok.status).toBe(200);
    expect(ok.text).toBe('777');
    expect((await request(ctx.app).get('/api/webhooks/whatsapp').query({ 'hub.mode': 'subscribe', 'hub.verify_token': 'wrong', 'hub.challenge': '1' })).status).toBe(403);
    expect((await request(ctx.app).get('/api/webhooks/whatsapp')).status).toBe(403);
  });
  it('rejects missing, malformed and wrong signatures and stores nothing', async () => {
    const body = payload([gm('sig1', '919800000001', 'should never be stored')]);
    expect((await request(ctx.app).post('/api/webhooks/whatsapp').set('Content-Type', 'application/json').send(JSON.stringify(body))).status).toBe(401);
    expect((await post(body, 'sha256=00')).status).toBe(401);
    expect((await post(body, 'sha256=' + crypto.createHmac('sha256', 'another-secret-another-secret').update(JSON.stringify(body)).digest('hex'))).status).toBe(401);
    expect(await prisma.chatMessage.count()).toBe(0);
  });
  it('rejects a body that was altered after signing', async () => {
    const raw = JSON.stringify(payload([gm('tamper', '919800000001', 'original')]));
    const r = await request(ctx.app).post('/api/webhooks/whatsapp').set('Content-Type', 'application/json').set('X-Hub-Signature-256', sign(raw)).send(raw.replace('original', 'changed!'));
    expect(r.status).toBe(401);
  });
});

describe('source mapping and permissions', () => {
  it('only project editors with upload permission can connect a conversation; duplicates conflict; outsiders see 404', async () => {
    const body = { phoneNumberId: PHONE, conversationKey: GROUP, label: 'Dev team group' };
    expect((await request(ctx.app).post(`/api/projects/${pid}/whatsapp-sources`).set(member.auth).send(body)).status).toBe(403);
    expect((await request(ctx.app).post(`/api/projects/${pid}/whatsapp-sources`).set(outsider.auth).send(body)).status).toBe(404);
    expect((await request(ctx.app).post(`/api/projects/${pid}/whatsapp-sources`).set(pm.auth).send({ ...body, phoneNumberId: 'abc' })).status).toBe(422);
    const ok = await request(ctx.app).post(`/api/projects/${pid}/whatsapp-sources`).set(pm.auth).send(body);
    expect(ok.status).toBe(201);
    const dup = await request(ctx.app).post(`/api/projects/${pid}/whatsapp-sources`).set(admin.auth).send(body);
    expect(dup.status).toBe(409);
    expect(JSON.stringify(dup.body)).not.toContain(pid);
    expect((await request(ctx.app).get(`/api/projects/${pid}/whatsapp-sources`).set(pm.auth)).body.items).toHaveLength(1);
    expect((await request(ctx.app).get(`/api/projects/${pid}/whatsapp-sources`).set(outsider.auth)).status).toBe(404);
  });
});

describe('ingestion', () => {
  it('stores mapped messages once, drops unmapped conversations, ignores reactions, and keeps the original text', async () => {
    const body = payload([
      gm('w1', '919800000001', 'Rahul, please integrate the payment API by Friday', t0),
      gm('w2', '919800000002', 'On it, will share the build tonight', t0 + 120, { context: { id: 'w1' } }),
      { id: 'w3', from: '919800000002', timestamp: String(t0 + 200), type: 'image', image: { mime_type: 'image/png', caption: 'screenshot' }, group_id: GROUP },
      { id: 'w4', from: '919800000001', timestamp: String(t0 + 300), type: 'reaction', reaction: { message_id: 'w2', emoji: '👍' }, group_id: GROUP },
      { ...gm('w5', '919800000009', 'someone else group'), group_id: 'GRP-not-mapped' },
    ]);
    const r1 = await post(body);
    expect(r1.status).toBe(200);
    expect(r1.body).toEqual({ received: 5, stored: 3, duplicates: 0, unmapped: 1, ignored: 1 });
    const again = await post(body);                                                         // Meta retries deliveries: must not duplicate
    expect(again.body).toEqual({ received: 5, stored: 0, duplicates: 3, unmapped: 1, ignored: 1 });
    const rows = await prisma.chatMessage.findMany({ where: { projectId: pid }, orderBy: { seq: 'asc' }, include: { sender: true } });
    expect(rows).toHaveLength(3);
    expect(rows.map((m) => m.sender?.displayName)).toEqual(['Priya', 'Rahul', 'Rahul']);
    expect(rows[0].originalText).toBe('Rahul, please integrate the payment API by Friday');
    expect(rows[0].timestamp.toISOString()).toBe('2026-10-01T10:00:00.000Z');              // wall clock in the project timezone
    expect(rows[2]).toMatchObject({ isMedia: true, messageType: 'MEDIA', text: '<Media omitted>\nscreenshot' });
    expect(rows[1].replyToId).toBe(rows[0].id);
    expect(rows[0].sender?.phone).not.toContain('919800000001');                           // phone numbers are stored encrypted
    expect(await prisma.chatMessage.count({ where: { text: { contains: 'someone else' } } })).toBe(0);
    const src = (await request(ctx.app).get(`/api/projects/${pid}/whatsapp-sources`).set(pm.auth)).body.items[0];
    expect(src.messageCount).toBe(3);
  });

  it('turns a burst of messages into one debounced analysis whose results appear in the dashboard', async () => {
    await wait(700);                                                                         // let the first batch's debounced job finish
    await ctx.queue.idle();
    const before = await prisma.analysisJob.count({ where: { projectId: pid } });
    for (let i = 0; i < 3; i++) await post(payload([gm(`burst${i}`, '919800000001', `Amit, please fix bug number ${i} by Monday`, t0 + 1000 + i * 60)]));
    await wait(700);
    await ctx.queue.idle();
    const jobs = await prisma.analysisJob.findMany({ where: { projectId: pid }, orderBy: { createdAt: 'asc' } });
    expect(jobs.length - before).toBe(1);                                                    // three webhooks, ONE analysis
    expect(jobs.at(-1)!.status).toBe('COMPLETED');
    const tasks = (await request(ctx.app).get(`/api/projects/${pid}/tasks`).set(pm.auth)).body.items;
    expect(tasks.length).toBeGreaterThan(0);
  });

  it('stops storing after the source is disconnected, but keeps what was stored', async () => {
    const src = (await request(ctx.app).get(`/api/projects/${pid}/whatsapp-sources`).set(pm.auth)).body.items[0];
    expect((await request(ctx.app).delete(`/api/projects/${pid}/whatsapp-sources/${src.id}`).set(member.auth)).status).toBe(403);
    expect((await request(ctx.app).delete(`/api/projects/${pid}/whatsapp-sources/${src.id}`).set(pm.auth)).status).toBe(204);
    const count = await prisma.chatMessage.count({ where: { projectId: pid } });
    const r = await post(payload([gm('after-disconnect', '919800000001', 'not stored')]));
    expect(r.body.unmapped).toBe(1);
    expect(await prisma.chatMessage.count({ where: { projectId: pid } })).toBe(count);
  });
});
