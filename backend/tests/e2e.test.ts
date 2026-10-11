import request from 'supertest';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { prisma } from '../src/db';
import { FULL, PART1 } from './fixtures';
import { bootstrapAdmin, createUser, makeCtx, resetDb, seedChat, Session, waitJob } from './helpers';

const ctx = makeCtx();
let admin: Session, pm: Session, dev: Session, sales: Session, client: Session, outsider: Session;
let projectId: string, otherProject: string;

beforeAll(async () => {
  await resetDb();
  admin = await bootstrapAdmin(ctx);
  pm = await createUser(ctx, admin, 'PROJECT_MANAGER', 'pm@example.com');
  dev = await createUser(ctx, admin, 'TEAM_MEMBER', 'dev@example.com');
  sales = await createUser(ctx, admin, 'SALES', 'sales@example.com');
  client = await createUser(ctx, admin, 'CLIENT_VIEWER', 'client@example.com');
  outsider = await createUser(ctx, admin, 'PROJECT_MANAGER', 'other-pm@example.com');
  const p = await request(ctx.app).post('/api/projects').set(pm.auth).send({ name: 'E-Commerce Website', clientName: 'Sharma Retail' });
  projectId = p.body.id;
  for (const u of [dev, sales, client]) {
    await request(ctx.app).post(`/api/projects/${projectId}/members`).set(pm.auth).send({ userId: u.user.id, canEdit: u === dev });
  }
  otherProject = (await request(ctx.app).post('/api/projects').set(outsider.auth).send({ name: 'Other' })).body.id;
});
afterAll(async () => { await ctx.queue.close(); await prisma.$disconnect(); });

const get = (u: Session, url: string) => request(ctx.app).get(url).set(u.auth);

describe('analysis pipeline', () => {
  it('re-analysis needs edit access, and a project without messages cannot be analysed', async () => {
    expect((await request(ctx.app).post(`/api/projects/${projectId}/chat/reanalyze`).set(pm.auth)).status).toBe(400);
    expect((await request(ctx.app).post(`/api/projects/${projectId}/chat/reanalyze`).set(client.auth)).status).toBe(403);
    expect((await request(ctx.app).post(`/api/projects/${projectId}/chat/reanalyze`).set(outsider.auth)).status).toBe(404);
  });

  let job1: string;
  it('returns 202 immediately and reports stage/progress, then completes', async () => {
    const r = await seedChat(ctx, pm.auth, projectId, PART1);
    expect(r.status).toBe(202);
    job1 = r.body.jobId;
    const early = (await get(pm, `/api/analysis/${job1}`)).body;
    expect(['QUEUED', 'RUNNING', 'COMPLETED']).toContain(early.status);
    const done = await waitJob(ctx, pm.auth, job1);
    expect(done).toMatchObject({ status: 'COMPLETED', progress: 100, stage: 'Completed', error: null });
  });

  it('stores original messages untouched and masks nothing it should not', async () => {
    const r = await get(pm, `/api/projects/${projectId}/messages?limit=100`);
    expect(r.status).toBe(200);
    expect(r.body.items).toHaveLength(11);
    const first = r.body.items[0];
    expect(first.sender.name).toBe('Rahul');
    expect(first.originalText).toBe('Amit, please integrate Razorpay by Friday.');
    expect(first.timestamp).toBe('2026-10-01T10:00:00.000Z'); // WhatsApp wall-clock preserved
    expect(first.id.startsWith(projectId + ':')).toBe(true);
  });

  it('extracts tasks with evidence and confidence', async () => {
    const t = (await get(pm, `/api/projects/${projectId}/tasks`)).body.items;
    const rz = t.find((x: any) => x.title.includes('Razorpay'));
    expect(rz).toMatchObject({ status: 'COMPLETED', assignee: { name: 'Amit' } });
    expect(rz.confidence).toBeGreaterThan(0.7);
    const login = t.find((x: any) => x.title.includes('login'));
    expect(login).toMatchObject({ status: 'BLOCKED', externalDependency: 'credentials' });
    const ev = (await get(pm, `/api/tasks/${rz.id}/evidence`)).body;
    expect(ev.evidence.length).toBeGreaterThanOrEqual(3);
    expect(ev.evidence.map((e: any) => e.text)).toContain('Razorpay API integrated.');
    expect(ev.evidence[0].context.length).toBeGreaterThan(0);
  });

  it('serves progress, health, client pending, requirement changes via analytics', async () => {
    const prog = (await get(pm, `/api/projects/${projectId}/progress?explain=true`)).body;
    expect(prog.overall).toBeGreaterThan(0);
    expect(prog.explanation.task_contributions.length).toBeGreaterThan(0);
    const health = (await get(pm, `/api/projects/${projectId}/health`)).body;
    expect(health.score).toBeGreaterThan(0);
    expect(['HEALTHY', 'AT_RISK', 'CRITICAL', 'BLOCKED']).toContain(health.status);
    const cp = (await get(pm, `/api/projects/${projectId}/client-pending`)).body.items;
    expect(cp.length).toBeGreaterThan(0);
    expect(cp[0].sourceMessageIds[0].startsWith(projectId + ':')).toBe(true);
    const summary = (await get(pm, `/api/projects/${projectId}/summary`)).body;
    expect(summary.text).toMatch(/Project is currently/);
    const versions = await prisma.requirementChange.findMany({ where: { requirement: { projectId } }, orderBy: { version: 'asc' } });
    expect(versions.map((v) => v.newValue)).toEqual(['stripe', 'razorpay']); // version history kept
    expect(versions[1].oldValue).toBe('stripe');
    const tl = (await get(pm, `/api/projects/${projectId}/timeline`)).body.items;
    expect(tl[0].type).toBe('START');
  });

  it('new messages are appended once and re-analysis does not duplicate tasks', async () => {
    const tasksBefore = await prisma.task.count({ where: { projectId } });
    const humanEdit = await prisma.task.findFirstOrThrow({ where: { projectId, title: { contains: 'login' } } });
    // human correction that must survive re-analysis
    const edit = await request(ctx.app).put(`/api/tasks/${humanEdit.id}`).set(pm.auth).send({ priority: 'CRITICAL', deadline: '2026-12-31T00:00:00Z' });
    expect(edit.status).toBe(200);

    const r = await seedChat(ctx, pm.auth, projectId, FULL);
    expect(r.status).toBe(202);
    expect((await waitJob(ctx, pm.auth, r.body.jobId)).status).toBe('COMPLETED');
    expect(await prisma.chatMessage.count({ where: { projectId, isSystem: false } })).toBe(23);
    const tasks = await prisma.task.findMany({ where: { projectId } });
    expect(tasks.length).toBeGreaterThan(tasksBefore); // new tasks from the new messages
    const titles = tasks.map((t) => t.title);
    expect(new Set(titles).size).toBe(titles.length); // no duplicates of earlier tasks
    const login = await prisma.task.findUniqueOrThrow({ where: { id: humanEdit.id } });
    expect(login.priority).toBe('CRITICAL'); // human override preserved
    expect(login.reviewState).toBe('HUMAN_CORRECTED');
    expect(login.deadline?.toISOString()).toBe('2026-12-31T00:00:00.000Z');
  });

  it('keeps a task history and change log for the human edit', async () => {
    const t = await prisma.task.findFirstOrThrow({ where: { projectId, title: { contains: 'login' } } });
    const hist = (await get(pm, `/api/tasks/${t.id}/history`)).body.items;
    expect(hist.some((h: any) => h.field === 'priority' && h.newValue === 'CRITICAL' && h.changedBy === pm.user.id)).toBe(true);
    const log = await prisma.changeLog.findFirstOrThrow({ where: { entityId: t.id, field: 'priority' } });
    expect(log.oldValue).not.toBe('CRITICAL');
    expect(log.newValue).toBe('CRITICAL');
    expect(log.changedById).toBe(pm.user.id);
  });

  it('manual role override survives re-analysis and never touches message text', async () => {
    const team = (await get(pm, `/api/projects/${projectId}/team`)).body.items;
    const karan = team.find((p: any) => p.name === 'Karan');
    const upd = await request(ctx.app).put(`/api/projects/${projectId}/team/${karan.id}`).set(pm.auth).send({ role: 'DESIGNER' });
    expect(upd.status).toBe(200);
    const re = await request(ctx.app).post(`/api/projects/${projectId}/chat/reanalyze`).set(pm.auth);
    expect(re.status).toBe(202);
    expect((await waitJob(ctx, pm.auth, re.body.jobId)).status).toBe('COMPLETED');
    const after = await prisma.chatParticipant.findUniqueOrThrow({ where: { id: karan.id } });
    expect(after.role).toBe('DESIGNER');
    expect(after.roleSource).toBe('admin');
    const msg = await prisma.chatMessage.findFirstOrThrow({ where: { projectId }, orderBy: { seq: 'asc' } });
    expect(msg.originalText).toBe('Amit, please integrate Razorpay by Friday.');
  });
});

describe('RBAC and project isolation', () => {
  it('non-members cannot see another project (404, not 403)', async () => {
    for (const url of [`/api/projects/${projectId}`, `/api/projects/${projectId}/tasks`, `/api/projects/${projectId}/messages`,
      `/api/projects/${projectId}/progress`, `/api/projects/${projectId}/reports`]) {
      expect((await get(outsider, url)).status).toBe(404);
    }
    const list = (await get(outsider, '/api/projects')).body.items;
    expect(list.map((p: any) => p.id)).toEqual([otherProject]);
    const task = await prisma.task.findFirstOrThrow({ where: { projectId } });
    expect((await get(outsider, `/api/tasks/${task.id}/evidence`)).status).toBe(404);
    expect((await request(ctx.app).put(`/api/tasks/${task.id}`).set(outsider.auth).send({ title: 'hacked' })).status).toBe(404);
    expect((await prisma.task.findUniqueOrThrow({ where: { id: task.id } })).title).not.toBe('hacked');
  });

  it('admins see all projects', async () => {
    expect((await get(admin, '/api/projects')).body.items.length).toBeGreaterThanOrEqual(2);
  });

  it('team member can only change task status, and only with edit access', async () => {
    const t = await prisma.task.findFirstOrThrow({ where: { projectId, status: 'TODO' } });
    expect((await request(ctx.app).put(`/api/tasks/${t.id}`).set(dev.auth).send({ title: 'rename' })).status).toBe(403);
    const ok = await request(ctx.app).put(`/api/tasks/${t.id}`).set(dev.auth).send({ status: 'IN_PROGRESS' });
    expect(ok.status).toBe(200);
    expect(ok.body.status).toBe('IN_PROGRESS');
    expect((await request(ctx.app).delete(`/api/tasks/${t.id}`).set(dev.auth)).status).toBe(403);
    // sales has read-only membership
    expect((await request(ctx.app).put(`/api/tasks/${t.id}`).set(sales.auth).send({ status: 'TODO' })).status).toBe(403);
  });

  it('sales sees sales + client-pending but not team performance; client viewer sees only client-facing data', async () => {
    expect((await get(sales, `/api/projects/${projectId}/sales`)).status).toBe(200);
    expect((await get(sales, `/api/projects/${projectId}/risks`)).status).toBe(403);
    expect((await get(dev, `/api/projects/${projectId}/sales`)).status).toBe(403);
    expect((await get(client, `/api/projects/${projectId}/messages`)).status).toBe(403);
    expect((await get(client, `/api/projects/${projectId}/team-performance`)).status).toBe(403);
    expect((await get(client, `/api/projects/${projectId}/risks`)).status).toBe(403);
    expect((await get(client, `/api/projects/${projectId}/search?q=payment`)).status).toBe(403);
    const health = (await get(client, `/api/projects/${projectId}/health`)).body;
    expect(Object.keys(health).sort()).toEqual(['computedAt', 'score', 'status']);
    const prog = (await get(client, `/api/projects/${projectId}/progress?explain=true`)).body;
    expect(prog.explanation).toBeUndefined();
    const tasks = (await get(client, `/api/projects/${projectId}/tasks`)).body.items;
    expect(Object.keys(tasks[0]).sort()).toEqual(['completedAt', 'deadline', 'id', 'status', 'title']);
    const tl = (await get(client, `/api/projects/${projectId}/timeline`)).body.items;
    expect(tl.every((e: any) => ['COMPLETED', 'CLIENT_PENDING', 'CLIENT_RESOLVED', 'DEPLOYMENT', 'MEETING', 'START'].includes(e.type))).toBe(true);
    expect(tl[0].sourceMessageIds).toBeUndefined();
  });

  it('only admins can delete projects and read the audit log', async () => {
    expect((await request(ctx.app).delete(`/api/projects/${otherProject}`).set(outsider.auth)).status).toBe(403);
    expect((await get(pm, '/api/audit')).status).toBe(403);
    const a = (await get(admin, '/api/audit?limit=200')).body.items.map((x: any) => x.action);
    for (const act of ['LOGIN', 'CREATE_PROJECT', 'CHANGE_MEMBER', 'VIEW_SENSITIVE', 'UPDATE_TASK', 'OVERRIDE_AI', 'REANALYZE']) expect(a).toContain(act);
  });

  it('paginates task and message lists', async () => {
    const p1 = (await get(pm, `/api/projects/${projectId}/messages?limit=5`)).body;
    expect(p1.items).toHaveLength(5);
    expect(p1.nextCursor).toBeTruthy();
    const p2 = (await get(pm, `/api/projects/${projectId}/messages?limit=5&cursor=${encodeURIComponent(p1.nextCursor)}`)).body;
    expect(p2.items[0].id).not.toBe(p1.items[0].id);
    expect(p2.items[0].seq).toBeGreaterThan(p1.items[4].seq - 100);
    const filt = (await get(pm, `/api/projects/${projectId}/messages?q=razorpay&sender=Amit`)).body.items;
    expect(filt.length).toBeGreaterThan(0);
    expect(filt.every((m: any) => m.sender.name === 'Amit')).toBe(true);
  });
});

describe('manual tasks, client pending edits, reports, search, notifications', () => {
  it('creates a manual task and edits a client-pending item with change log', async () => {
    const t = await request(ctx.app).post(`/api/projects/${projectId}/tasks`).set(pm.auth).send({ title: 'Prepare UAT checklist', priority: 'HIGH' });
    expect(t.status).toBe(201);
    expect(t.body.reviewState).toBe('HUMAN_CONFIRMED');
    const cp = await prisma.clientPendingItem.findFirstOrThrow({ where: { projectId, status: 'OPEN' } });
    const upd = await request(ctx.app).put(`/api/client-pending/${cp.id}`).set(sales.auth).send({ status: 'RESOLVED' });
    expect(upd.status).toBe(403); // sales membership is read-only on this project
    const upd2 = await request(ctx.app).put(`/api/client-pending/${cp.id}`).set(pm.auth).send({ status: 'RESOLVED' });
    expect(upd2.status).toBe(200);
    expect(upd2.body.resolvedAt).toBeTruthy();
    const re = await request(ctx.app).post(`/api/projects/${projectId}/chat/reanalyze`).set(pm.auth);
    await waitJob(ctx, pm.auth, re.body.jobId);
    expect((await prisma.clientPendingItem.findUniqueOrThrow({ where: { id: cp.id } })).status).toBe('RESOLVED'); // human override kept
    expect(await prisma.task.count({ where: { projectId, title: 'Prepare UAT checklist' } })).toBe(1); // manual task kept
  });

  it('generates a report and exports pdf / xlsx / csv / json', async () => {
    const g = await request(ctx.app).post(`/api/projects/${projectId}/reports/generate`).set(pm.auth).send({ kind: 'FULL', company: 'Acme Tech' });
    expect(g.status).toBe(201);
    expect((await get(pm, `/api/projects/${projectId}/reports`)).body.items).toHaveLength(1);
    const json = (await get(pm, `/api/reports/${g.body.id}`)).body;
    expect(json.content.meta.company).toBe('Acme Tech');
    expect(json.content['13_client_pending'].length).toBeGreaterThan(0);
    for (const [fmt, magic] of [['pdf', '%PDF'], ['xlsx', 'PK'], ['csv', 'Task']] as const) {
      const r = await request(ctx.app).get(`/api/reports/${g.body.id}?format=${fmt}`).set(pm.auth).buffer(true).parse((res, cb) => {
        const chunks: Buffer[] = []; res.on('data', (c: Buffer) => chunks.push(c)); res.on('end', () => cb(null, Buffer.concat(chunks)));
      });
      expect(r.status).toBe(200);
      expect((r.body as Buffer).subarray(0, 4).toString()).toContain(magic.slice(0, 2));
    }
    expect((await get(pm, `/api/reports/${g.body.id}?format=exe`)).status).toBe(422);
    expect((await get(outsider, `/api/reports/${g.body.id}`)).status).toBe(404);
    expect((await request(ctx.app).post(`/api/projects/${projectId}/reports/generate`).set(dev.auth).send({})).status).toBe(403);
    const audit = await prisma.auditLog.findMany({ where: { projectId, action: 'GENERATE_REPORT' } });
    expect(audit).toHaveLength(1);
  });

  it('semantic search returns original messages with project-scoped ids', async () => {
    const r = await get(pm, `/api/projects/${projectId}/search?q=payment&mode=lexical`);
    expect(r.status).toBe(200);
    expect(r.body.hits.length).toBeGreaterThan(0);
    expect(r.body.hits.every((h: any) => h.message_id.startsWith(projectId + ':'))).toBe(true);
    expect(r.body.hits.some((h: any) => /Razorpay/.test(h.text))).toBe(true);
  });

  it('creates notifications for new client-pending items / risks / requirement changes', async () => {
    const mine = (await get(pm, '/api/notifications')).body;
    expect(mine.unread).toBeGreaterThan(0);
    expect(mine.items.some((n: any) => n.type === 'CLIENT_PENDING_NEW')).toBe(true);
    expect(mine.items.some((n: any) => n.type === 'REQUIREMENT_CHANGE')).toBe(true);
    expect((await get(dev, '/api/notifications')).body.items).toHaveLength(0); // team members are not notified
    await request(ctx.app).post('/api/notifications/read-all').set(pm.auth);
    expect((await get(pm, '/api/notifications')).body.unread).toBe(0);
  });
});

describe('project deletion', () => {
  it('deleting a project removes all of its data and nothing else', async () => {
    const before = await prisma.chatMessage.count({ where: { projectId: { not: projectId } } });
    expect((await request(ctx.app).delete(`/api/projects/${projectId}`).set(admin.auth)).status).toBe(204);
    expect(await prisma.chatMessage.count({ where: { projectId } })).toBe(0);
    expect(await prisma.task.count({ where: { projectId } })).toBe(0);
    expect(await prisma.chatMessage.count({ where: { projectId: { not: projectId } } })).toBe(before);
  });
});
