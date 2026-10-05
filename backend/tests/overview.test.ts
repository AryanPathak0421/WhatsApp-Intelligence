import request from 'supertest';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { prisma } from '../src/db';
import { FULL } from './fixtures';
import { bootstrapAdmin, createUser, makeCtx, resetDb, Session, uploadChat, waitJob } from './helpers';

const ctx = makeCtx();
let admin: Session, pm: Session, client: Session, outsider: Session, pA: string, pB: string;
beforeAll(async () => {
  await resetDb();
  admin = await bootstrapAdmin(ctx);
  pm = await createUser(ctx, admin, 'PROJECT_MANAGER', 'pm@example.com');
  client = await createUser(ctx, admin, 'CLIENT_VIEWER', 'client@example.com');
  outsider = await createUser(ctx, admin, 'PROJECT_MANAGER', 'o@example.com');
  pA = (await request(ctx.app).post('/api/projects').set(pm.auth).send({ name: 'Alpha', clientName: 'Acme' })).body.id;
  pB = (await request(ctx.app).post('/api/projects').set(outsider.auth).send({ name: 'Beta' })).body.id;
  await request(ctx.app).post(`/api/projects/${pA}/members`).set(pm.auth).send({ userId: client.user.id });
  const up = await uploadChat(ctx, pm.auth, pA, FULL);
  await waitJob(ctx, pm.auth, up.body.jobId);
});
afterAll(async () => { await ctx.queue.close(); await prisma.$disconnect(); });

describe('overview + executive', () => {
  it('project overview aggregates counts from the stored analysis', async () => {
    const o = (await request(ctx.app).get(`/api/projects/${pA}/overview`).set(pm.auth)).body;
    expect(o.project).toMatchObject({ name: 'Alpha', client: 'Acme' });
    expect(o.progress.overall).toBeGreaterThan(0);
    expect(o.health.status).toBeDefined();
    const total = Object.values(o.tasks as Record<string, number>).reduce((a, b) => a + b, 0);
    expect(total).toBe(await prisma.task.count({ where: { projectId: pA } }));
    expect(o.tasks.COMPLETED).toBeGreaterThan(0);
    expect(o.clientPendingOpen).toBeGreaterThan(0);
    expect(o.overdue).toBeGreaterThan(0);
    expect(o.risksBySeverity).toBeDefined();
    expect(o.lastAnalysis.status).toBe('COMPLETED');
  });

  it('client viewers get a reduced overview', async () => {
    const o = (await request(ctx.app).get(`/api/projects/${pA}/overview`).set(client.auth)).body;
    expect(o.tasks).toBeDefined();
    expect(o.risksBySeverity).toBeUndefined();
    expect(o.openBugs).toBeUndefined();
    expect(o.participants).toBeUndefined();
    expect((await request(ctx.app).get(`/api/projects/${pB}/overview`).set(client.auth)).status).toBe(404);
  });

  it('executive dashboard only covers projects the caller can access', async () => {
    const mine = (await request(ctx.app).get('/api/executive').set(pm.auth)).body;
    expect(mine.projects.map((p: any) => p.name)).toEqual(['Alpha']);
    expect(mine.totals.projects).toBe(1);
    expect(mine.totals.averageProgress).toBeGreaterThan(0);
    expect(mine.totals.clientPending).toBeGreaterThan(0);
    expect(mine.totals.teamUtilization).toBeGreaterThan(0);
    const all = (await request(ctx.app).get('/api/executive').set(admin.auth)).body;
    expect(all.projects.map((p: any) => p.name).sort()).toEqual(['Alpha', 'Beta']);
    expect(all.projects.find((p: any) => p.name === 'Beta').progress).toBeNull(); // no fake numbers for un-analysed projects
    expect((await request(ctx.app).get('/api/executive').set(client.auth)).status).toBe(403);
  });

  it('user list is admin-only', async () => {
    expect((await request(ctx.app).get('/api/users').set(admin.auth)).body.items.length).toBe(4);
    expect((await request(ctx.app).get('/api/users').set(pm.auth)).status).toBe(403);
  });
});
