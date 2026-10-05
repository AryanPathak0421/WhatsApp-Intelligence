import request from 'supertest';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { prisma } from '../src/db';
import { bootstrapAdmin, createUser, makeCtx, resetDb, Session, uploadChat, waitJob } from './helpers';

const CHAT = `[01/10/2026, 10:00 AM] Priya: Rahul, when will the invoice export be ready?
[01/10/2026, 10:05 AM] Rahul: The invoice export will be ready by Friday
[01/10/2026, 10:30 AM] Priya: This is wrong again, the payment page is still not working!!!
[01/10/2026, 11:00 AM] Rahul: Thanks for flagging, fixing the payment page now
[02/10/2026, 09:00 AM] Priya: Rahul, please add the admin dashboard filters
[08/10/2026, 09:00 AM] Priya: Who owns the reporting module?
`;

const ctx = makeCtx();
let admin: Session, pm: Session, member: Session, client: Session, outsider: Session;
let pid: string;

beforeAll(async () => {
  await resetDb();
  admin = await bootstrapAdmin(ctx);
  pm = await createUser(ctx, admin, 'PROJECT_MANAGER', 'pm@example.com');
  member = await createUser(ctx, admin, 'TEAM_MEMBER', 'member@example.com');
  client = await createUser(ctx, admin, 'CLIENT_VIEWER', 'client@example.com');
  outsider = await createUser(ctx, admin, 'PROJECT_MANAGER', 'other@example.com');
  pid = (await request(ctx.app).post('/api/projects').set(pm.auth).send({ name: 'Insights' })).body.id;
  for (const u of [member, client]) await request(ctx.app).post(`/api/projects/${pid}/members`).set(pm.auth).send({ userId: u.user.id });
  const up = await uploadChat(ctx, pm.auth, pid, CHAT);
  expect(up.status).toBe(202);
  const job = await waitJob(ctx, pm.auth, up.body.jobId);
  expect(job.status).toBe('COMPLETED');
});
afterAll(async () => { await ctx.queue.close(); await prisma.$disconnect(); });

const get = (u: Session, url: string) => request(ctx.app).get(url).set(u.auth);

describe('question/answer analytics', () => {
  it('returns counts and evidence-linked items, filterable by status', async () => {
    const r = await get(member, `/api/projects/${pid}/qa`);
    expect(r.status).toBe(200);
    expect(r.body.stats.total_questions).toBe(2);
    const answered = r.body.items.find((i: any) => i.text.includes('invoice export'));
    expect(answered.status).toBe('ANSWERED');
    expect(answered.evidence_message_ids.length).toBe(2);
    const open = (await get(member, `/api/projects/${pid}/qa?status=UNANSWERED`)).body.items;
    expect(open.length).toBeGreaterThanOrEqual(1);
    expect(open.every((i: any) => i.status === 'UNANSWERED')).toBe(true);
  });
  it('is not available to client viewers, outsiders, or without a token; bad filters are rejected', async () => {
    expect((await get(client, `/api/projects/${pid}/qa`)).status).toBe(403);
    expect((await get(outsider, `/api/projects/${pid}/qa`)).status).toBe(404);
    expect((await request(ctx.app).get(`/api/projects/${pid}/qa`)).status).toBe(401);
    expect((await get(member, `/api/projects/${pid}/qa?status=MAYBE`)).status).toBe(422);
  });
});

describe('sentiment', () => {
  it('flags the frustrated message with its evidence and labels the method as a baseline', async () => {
    const r = await get(member, `/api/projects/${pid}/sentiment`);
    expect(r.status).toBe(200);
    expect(r.body.counts.frustrated).toBeGreaterThanOrEqual(1);
    expect(r.body.method).toMatch(/lexicon baseline/);
    expect(r.body.items[0].evidence.length).toBeGreaterThan(0);
    expect((await get(client, `/api/projects/${pid}/sentiment`)).status).toBe(403);
  });
});

describe('periodic summaries', () => {
  it('serves day, week and month levels newest first with source ids on every highlight', async () => {
    for (const kind of ['daily', 'weekly', 'monthly']) {
      const r = await get(member, `/api/projects/${pid}/summaries?kind=${kind}`);
      expect(r.status).toBe(200);
      expect(r.body.items.length).toBeGreaterThan(0);
      for (const it of r.body.items) for (const h of it.highlights) expect(h.source_message_ids.length).toBeGreaterThan(0);
    }
    const weekly = (await get(member, `/api/projects/${pid}/summaries?kind=weekly`)).body.items;
    expect(weekly.length).toBe(2);
    expect(weekly[0].key > weekly[1].key).toBe(true);
    expect((await get(member, `/api/projects/${pid}/summaries?kind=yearly`)).status).toBe(422);
    expect((await get(client, `/api/projects/${pid}/summaries`)).status).toBe(403);
  });
});
