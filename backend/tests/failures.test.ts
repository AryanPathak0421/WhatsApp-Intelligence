import IORedis from 'ioredis';
import { Queue } from 'bullmq';
import request from 'supertest';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { loadConfig, resetConfigForTests } from '../src/config';
import { prisma } from '../src/db';
import { QUEUE_NAME, startWorker } from '../src/queues';
import { PART1 } from './fixtures';
import { bootstrapAdmin, createUser, makeCtx, resetDb, seedChat, Session, waitJob } from './helpers';

const REDIS = process.env.TEST_REDIS_URL ?? 'redis://localhost:56379';
const saved = { ...process.env };
afterEach(() => { process.env = { ...saved }; resetConfigForTests(); });

let admin: Session, pm: Session;
beforeAll(async () => {
  const ctx = makeCtx();
  await resetDb();
  admin = await bootstrapAdmin(ctx);
  pm = await createUser(ctx, admin, 'PROJECT_MANAGER', 'pm@example.com');
  await ctx.queue.close();
});
afterAll(async () => { await prisma.$disconnect(); });

const newProject = async (ctx: ReturnType<typeof makeCtx>) =>
  (await request(ctx.app).post('/api/projects').set(pm.auth).send({ name: 'P' + Math.random() })).body.id as string;

describe('configuration', () => {
  it('fails fast and names the missing/invalid variables without printing secrets', () => {
    expect(() => loadConfig({ NODE_ENV: 'production', DATABASE_URL: 'postgresql://x', JWT_ACCESS_SECRET: 'short-secret-value' } as never))
      .toThrowError(/JWT_ACCESS_SECRET|JWT_REFRESH_SECRET|FIELD_ENCRYPTION_KEY/);
    try { loadConfig({ DATABASE_URL: 'x', JWT_ACCESS_SECRET: 'super-sensitive-value-1234567890-abcdefgh', JWT_REFRESH_SECRET: 'a', FIELD_ENCRYPTION_KEY: 'nothex' } as never); }
    catch (e) { expect(String(e)).not.toContain('super-sensitive'); }
  });
  it('defaults to inline queue without Redis and bullmq with it', () => {
    const base = { DATABASE_URL: 'x', JWT_ACCESS_SECRET: 'a'.repeat(32), JWT_REFRESH_SECRET: 'b'.repeat(32), FIELD_ENCRYPTION_KEY: 'c'.repeat(64) };
    expect(loadConfig(base as never).queueMode).toBe('inline');
    expect(loadConfig({ ...base, REDIS_URL: REDIS } as never).queueMode).toBe('bullmq');
  });
});

describe('failure handling (user-facing errors are sanitized)', () => {
  it('marks the job FAILED when the AI service is unavailable, without leaking internals', async () => {
    process.env.AI_ENGINE_URL = 'http://127.0.0.1:1';
    resetConfigForTests();
    const ctx = makeCtx();
    const pid = await newProject(ctx);
    const r = await seedChat(ctx, pm.auth, pid, PART1);
    expect(r.status).toBe(202);
    const job = await waitJob(ctx, pm.auth, r.body.jobId);
    expect(job.status).toBe('FAILED');
    expect(job.error).toBe('Analysis service is unavailable');
    expect(JSON.stringify(job)).not.toMatch(/127\.0\.0\.1|ECONNREFUSED|axios|at /);
    // the project stays usable: a retry after the service returns works
    process.env.AI_ENGINE_URL = saved.AI_ENGINE_URL!;
    resetConfigForTests();
    const re = await seedChat(ctx, pm.auth, pid, PART1 + '[03/10/2026, 10:00 AM] Rahul: ok\n');
    expect(re.status).toBe(202);
    expect((await waitJob(ctx, pm.auth, re.body.jobId)).status).toBe('COMPLETED');
    await ctx.queue.close();
  });

  it('treats a wrong service token as a generic analysis failure', async () => {
    process.env.AI_ENGINE_TOKEN = 'wrong-token';
    resetConfigForTests();
    const ctx = makeCtx();
    const pid = await newProject(ctx);
    const r = await seedChat(ctx, pm.auth, pid, PART1);
    const job = await waitJob(ctx, pm.auth, r.body.jobId);
    expect(job.status).toBe('FAILED');
    expect(job.error).toBe('Analysis failed');
    await ctx.queue.close();
  });

  it('times out slow analysis cleanly', async () => {
    process.env.AI_TIMEOUT_MS = '1';
    resetConfigForTests();
    const ctx = makeCtx();
    const pid = await newProject(ctx);
    const r = await seedChat(ctx, pm.auth, pid, PART1);
    const job = await waitJob(ctx, pm.auth, r.body.jobId);
    expect(job.status).toBe('FAILED');
    expect(['Analysis timed out', 'Analysis service is unavailable']).toContain(job.error);
    await ctx.queue.close();
  });

  it('refuses a second analysis while one is running', async () => {
    const ctx = makeCtx();
    const pid = await newProject(ctx);
    await prisma.analysisJob.create({ data: { projectId: pid, status: 'RUNNING', stage: 'Analyzing project', progress: 45 } });
    const r = await seedChat(ctx, pm.auth, pid, PART1);
    expect(r.status).toBe(409);
    expect(r.body.error.code).toBe('ANALYSIS_IN_PROGRESS');
    await ctx.queue.close();
  });

  it('health endpoint reports ok when the database is reachable', async () => {
    const ctx = makeCtx();
    expect((await request(ctx.app).get('/health')).body).toEqual({ status: 'ok' });
    await ctx.queue.close();
  });
});

describe('BullMQ queue (real Redis)', () => {
  it('processes an analysis through Redis + a separate worker', async () => {
    const probe = new IORedis(REDIS, { maxRetriesPerRequest: 1, retryStrategy: () => null });
    try { await probe.ping(); } catch { probe.disconnect(); console.warn('Redis unavailable - skipping BullMQ test'); return; }
    process.env.QUEUE_MODE = 'bullmq';
    process.env.REDIS_URL = REDIS;
    resetConfigForTests();
    const ctx = makeCtx();
    const w = startWorker(1);
    try {
      const pid = await newProject(ctx);
      const r = await seedChat(ctx, pm.auth, pid, PART1);
      expect(r.status).toBe(202);
      let job: any;
      for (let i = 0; i < 120; i++) {
        job = (await request(ctx.app).get(`/api/analysis/${r.body.jobId}`).set(pm.auth)).body;
        if (['COMPLETED', 'FAILED'].includes(job.status)) break;
        await new Promise((s) => setTimeout(s, 500));
      }
      expect(job.status).toBe('COMPLETED');
      expect(await prisma.task.count({ where: { projectId: pid } })).toBeGreaterThan(0);
    } finally {
      await w.close();
      await ctx.queue.close();
      const q = new Queue(QUEUE_NAME, { connection: probe });
      await q.obliterate({ force: true });
      await q.close();
      probe.disconnect();
    }
  });
});
