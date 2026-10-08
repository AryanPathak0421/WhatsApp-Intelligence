import request from 'supertest';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { prisma } from '../src/db';
import { assess } from '../src/services/reliability';
import { bootstrapAdmin, createUser, makeCtx, resetDb, Session } from './helpers';

const t = (confidence: number, needsReview: boolean) => ({ confidence, needsReview });
const many = (n: number, c: number, nr: boolean) => Array.from({ length: n }, () => t(c, nr));

describe('assess (pure)', () => {
  it('is INSUFFICIENT before analysis and with fewer than 3 tasks', () => {
    expect(assess({ analysed: false, tasks: many(10, 0.9, false), messages: 500 }).level).toBe('INSUFFICIENT');
    expect(assess({ analysed: true, tasks: many(2, 0.9, false), messages: 500 })).toMatchObject({ level: 'INSUFFICIENT', tasks: 2 });
  });
  it('is LOW for the Get-Right-Home pattern: few tasks, all low-confidence, all awaiting review', () => {
    const r = assess({ analysed: true, tasks: many(9, 0.6, true), messages: 440 });
    expect(r.level).toBe('LOW');
    expect(r.reasons.join(' ')).toMatch(/9 of 9 tasks/);
    expect(r.reasons.join(' ')).toMatch(/9 tasks were found in 440 messages/);
    expect(r.tasksPer100Messages).toBeCloseTo(2, 0);
  });
  it('is MEDIUM when some tasks need review, and HIGH when the evidence is solid', () => {
    expect(assess({ analysed: true, tasks: [...many(4, 0.9, false), ...many(3, 0.7, true)], messages: 100 }).level).toBe('MEDIUM');
    expect(assess({ analysed: true, tasks: many(12, 0.9, false), messages: 150 })).toMatchObject({ level: 'HIGH', reasons: [] });
  });
  it('rises as a person confirms tasks (needsReview false) without any re-analysis', () => {
    expect(assess({ analysed: true, tasks: many(6, 0.6, true), messages: 60 }).level).toBe('LOW');
    expect(assess({ analysed: true, tasks: many(6, 0.95, false), messages: 60 }).level).toBe('HIGH');
  });
  it('does not penalise a small chat for a low task rate', () => {
    expect(assess({ analysed: true, tasks: many(4, 0.9, false), messages: 40 }).level).toBe('HIGH');
  });
});

describe('API', () => {
  const ctx = makeCtx();
  let admin: Session, viewer: Session;
  let thin: string, solid: string;
  const seed = async (name: string, n: number, conf: number, review: 'NEEDS_REVIEW' | 'HUMAN_CONFIRMED', completed: number) => {
    const p = await prisma.project.create({ data: { name, managerId: admin.user.id, members: { create: { userId: admin.user.id, canView: true, canEdit: true } } } });
    await prisma.projectProgress.create({ data: { projectId: p.id, overall: 80, development: 80, completedWeight: 4, totalWeight: 5, explanation: {} } });
    await prisma.projectHealth.create({ data: { projectId: p.id, score: 40, status: 'CRITICAL', components: {} } });
    for (let i = 0; i < n; i++) {
      await prisma.task.create({ data: { projectId: p.id, title: `Task number ${i} for ${name}`, status: i < completed ? 'COMPLETED' : 'TODO', confidence: conf, reviewState: review, priority: 'MEDIUM', domain: 'DEVELOPMENT', weight: 2 } });
    }
    return p.id;
  };

  beforeAll(async () => {
    await resetDb();
    admin = await bootstrapAdmin(ctx);
    viewer = await createUser(ctx, admin, 'CLIENT_VIEWER', 'viewer@example.com');
    thin = await seed('Thin evidence', 5, 0.55, 'NEEDS_REVIEW', 4);
    solid = await seed('Solid evidence', 10, 0.95, 'HUMAN_CONFIRMED', 6);
    await prisma.projectMember.create({ data: { projectId: thin, userId: viewer.user.id, canView: true } });
  });
  afterAll(async () => { await ctx.queue.close(); await prisma.$disconnect(); });

  it('overview carries the level and the reasons for internal users; client viewers get the level only', async () => {
    const a = (await request(ctx.app).get(`/api/projects/${thin}/overview`).set(admin.auth)).body;
    expect(a.reliability.level).toBe('LOW');
    expect(a.reliability.reasons.length).toBeGreaterThan(0);
    const v = (await request(ctx.app).get(`/api/projects/${thin}/overview`).set(viewer.auth)).body;
    expect(v.reliability).toEqual({ level: 'LOW', reasons: [] });
    expect((await request(ctx.app).get(`/api/projects/${solid}/overview`).set(admin.auth)).body.reliability.level).toBe('HIGH');
  });

  it('the executive view keeps shaky projects out of the at-risk/critical counts and the average progress, and says how many it left out', async () => {
    const ex = (await request(ctx.app).get('/api/executive').set(admin.auth)).body;
    expect(ex.totals.critical).toBe(1);                       // only the project with solid evidence counts
    expect(ex.totals.lowConfidence).toBe(1);
    expect(ex.totals.averageProgress).toBe(80);
    expect(ex.projects.find((p: any) => p.id === thin).reliability).toBe('LOW');
    expect(ex.projects.find((p: any) => p.id === solid).reliability).toBe('HIGH');
  });

  it('confirming tasks raises the level at once', async () => {
    await prisma.task.updateMany({ where: { projectId: thin }, data: { reviewState: 'HUMAN_CONFIRMED', confidence: 0.95 } });
    expect((await request(ctx.app).get(`/api/projects/${thin}/overview`).set(admin.auth)).body.reliability.level).toBe('HIGH');
  });
});
