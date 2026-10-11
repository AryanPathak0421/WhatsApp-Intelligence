import request from 'supertest';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { prisma } from '../src/db';
import { runRetentionSweep } from '../src/services/retention';
import { bootstrapAdmin, createUser, makeCtx, resetDb, seedChat, Session, waitJob } from './helpers';

const DAY = 86_400_000;
const ddmmyyyy = (daysAgo: number) => { const d = new Date(Date.now() - daysAgo * DAY); return `${String(d.getUTCDate()).padStart(2, '0')}/${String(d.getUTCMonth() + 1).padStart(2, '0')}/${d.getUTCFullYear()}`; };
const chat = () => `[${ddmmyyyy(100)}, 10:00 AM] Priya: Rahul, please build the old login page by Friday
[${ddmmyyyy(100)}, 11:00 AM] Rahul: login page is done
[${ddmmyyyy(2)}, 10:00 AM] Priya: Rahul, please add the invoice export by Monday
[${ddmmyyyy(2)}, 11:00 AM] Rahul: working on the invoice export
`;
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

const ctx = makeCtx();
let admin: Session, pm: Session, member: Session, outsider: Session;
let pid: string;
const get = (u: Session, url: string) => request(ctx.app).get(url).set(u.auth);

async function freshProject(name: string) {
  const id = (await request(ctx.app).post('/api/projects').set(pm.auth).send({ name })).body.id;
  const up = await seedChat(ctx, pm.auth, id, chat());
  expect(up.status).toBe(202);
  expect((await waitJob(ctx, pm.auth, up.body.jobId)).status).toBe('COMPLETED');
  return id as string;
}

beforeAll(async () => {
  await resetDb();
  admin = await bootstrapAdmin(ctx);
  pm = await createUser(ctx, admin, 'PROJECT_MANAGER', 'pm@example.com');
  member = await createUser(ctx, admin, 'TEAM_MEMBER', 'member@example.com');
  outsider = await createUser(ctx, admin, 'PROJECT_MANAGER', 'other@example.com');
  pid = await freshProject('Retention');
  await request(ctx.app).post(`/api/projects/${pid}/members`).set(pm.auth).send({ userId: member.user.id });
});
afterAll(async () => { await wait(300); await ctx.queue.close(); await prisma.$disconnect(); });

describe('retention policy', () => {
  it('can be read and set only by editors, with sane bounds, and is audited', async () => {
    expect((await get(pm, `/api/projects/${pid}/retention`)).body.retentionDays).toBeNull();
    expect((await request(ctx.app).put(`/api/projects/${pid}/retention`).set(member.auth).send({ retentionDays: 90 })).status).toBe(403);
    expect((await request(ctx.app).put(`/api/projects/${pid}/retention`).set(outsider.auth).send({ retentionDays: 90 })).status).toBe(404);
    expect((await request(ctx.app).put(`/api/projects/${pid}/retention`).set(pm.auth).send({ retentionDays: 5 })).status).toBe(422);
    expect((await request(ctx.app).put(`/api/projects/${pid}/retention`).set(pm.auth).send({ retentionDays: 30 })).status).toBe(200);
    expect((await get(pm, `/api/projects/${pid}/retention`)).body.retentionDays).toBe(30);
    expect(await prisma.auditLog.count({ where: { action: 'SET_RETENTION' } })).toBe(1);
  });

  it('purges messages older than the policy and rebuilds derived data from what remains', async () => {
    const before = await prisma.chatMessage.count({ where: { projectId: pid } });
    expect(before).toBe(4);
    expect((await prisma.task.findMany({ where: { projectId: pid } })).some((t) => /login/i.test(t.title))).toBe(true);
    const r = await request(ctx.app).post(`/api/projects/${pid}/retention/purge`).set(pm.auth);
    expect(r.status).toBe(200);
    expect(r.body).toMatchObject({ messagesDeleted: 2, remainingMessages: 2, reanalysisScheduled: true, derivedWiped: false });
    await wait(500);
    await ctx.queue.idle();
    const rows = await prisma.chatMessage.findMany({ where: { projectId: pid } });
    expect(rows.every((m) => /invoice/i.test(m.text))).toBe(true);
    const tasks = await prisma.task.findMany({ where: { projectId: pid } });
    expect(tasks.some((t) => /login/i.test(t.title))).toBe(false);          // the task that came from deleted messages is gone after re-analysis
    expect(tasks.some((t) => /invoice/i.test(t.title))).toBe(true);
    const snaps = await prisma.aIAnalysis.groupBy({ by: ['kind'], where: { projectId: pid }, _count: { _all: true } });
    expect(snaps.every((s) => s._count._all <= 2)).toBe(true);               // no pile of stale snapshots
  });

  it('refuses to purge when no policy is set', async () => {
    const p2 = await freshProject('No policy');
    expect((await request(ctx.app).post(`/api/projects/${p2}/retention/purge`).set(pm.auth)).status).toBe(400);
  });

  it('the scheduled sweep applies every project policy', async () => {
    const p3 = await freshProject('Sweep');
    await prisma.project.update({ where: { id: p3 }, data: { retentionDays: 30 } });
    const out = await runRetentionSweep(ctx.queue);
    expect(out.projects).toBeGreaterThanOrEqual(1);
    expect(await prisma.chatMessage.count({ where: { projectId: p3, timestamp: { lt: new Date(Date.now() - 31 * DAY) } } })).toBe(0);
    expect(await prisma.chatMessage.count({ where: { projectId: p3 } })).toBe(2);
    await wait(500);
    await ctx.queue.idle();
  });
});

describe('erasure', () => {
  it('needs the delete permission and the exact project name', async () => {
    const p4 = await freshProject('Erase me');
    expect((await request(ctx.app).post(`/api/projects/${p4}/erase-data`).set(pm.auth).send({ confirmProjectName: 'Erase me' })).status).toBe(403);   // PMs cannot delete data
    expect((await request(ctx.app).post(`/api/projects/${p4}/erase-data`).set(admin.auth).send({ confirmProjectName: 'erase me' })).status).toBe(400);
    expect((await request(ctx.app).post(`/api/projects/${p4}/erase-data`).set(admin.auth).send({})).status).toBe(422);
    expect(await prisma.chatMessage.count({ where: { projectId: p4 } })).toBe(4);
  });

  it('removes messages, derived data, snapshots and participants but keeps the project shell and the audit trail', async () => {
    const p5 = await freshProject('Erase fully');
    expect(await prisma.task.count({ where: { projectId: p5 } })).toBeGreaterThan(0);
    const r = await request(ctx.app).post(`/api/projects/${p5}/erase-data`).set(admin.auth).send({ confirmProjectName: 'Erase fully' });
    expect(r.status).toBe(200);
    expect(r.body).toMatchObject({ messagesDeleted: 4, derivedWiped: true, uploadFilesDeleted: 0 });   // in-app messages have no files
    for (const model of ['chatMessage', 'task', 'chatParticipant', 'aIAnalysis', 'insight', 'projectProgress', 'projectHealth', 'analysisJob'] as const) {
      expect(await (prisma as any)[model].count({ where: { projectId: p5 } }), model).toBe(0);
    }
    expect(await prisma.project.count({ where: { id: p5 } })).toBe(1);
    expect(await prisma.auditLog.count({ where: { action: 'ERASE_PROJECT_DATA', projectId: p5 } })).toBe(1);
    expect((await get(pm, `/api/projects/${p5}/tasks`)).body.items).toEqual([]);
  });
});
