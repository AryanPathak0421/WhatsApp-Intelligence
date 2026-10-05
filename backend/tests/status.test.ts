import request from 'supertest';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { prisma } from '../src/db';
import { bootstrapAdmin, createUser, makeCtx, resetDb, Session } from './helpers';

const ctx = makeCtx();
let admin: Session, pm: Session;

beforeAll(async () => {
  await resetDb();
  admin = await bootstrapAdmin(ctx);
  pm = await createUser(ctx, admin, 'PROJECT_MANAGER', 'pm@example.com');
});
afterAll(async () => { await ctx.queue.close(); await prisma.$disconnect(); });

describe('health, readiness and status', () => {
  it('health and ready are public and expose booleans only', async () => {
    expect((await request(ctx.app).get('/api/health')).body).toEqual({ status: 'ok' });
    const r = await request(ctx.app).get('/api/ready');
    expect(r.status).toBe(200);
    expect(r.body).toEqual({ status: 'ready', db: true, queue: true, ai: true });
  });
  it('queue and AI status are admin-only and report mode, depth and model information', async () => {
    expect((await request(ctx.app).get('/api/queue/status')).status).toBe(401);
    expect((await request(ctx.app).get('/api/queue/status').set(pm.auth)).status).toBe(403);
    expect((await request(ctx.app).get('/api/ai/status').set(pm.auth)).status).toBe(403);
    const q = await request(ctx.app).get('/api/queue/status').set(admin.auth);
    expect(q.status).toBe(200);
    expect(q.body.mode).toBe('inline');
    expect(q.body).toHaveProperty('jobsByStatus');
    const a = await request(ctx.app).get('/api/ai/status').set(admin.auth);
    expect(a.status).toBe(200);
    expect(a.body.reachable).toBe(true);
  });
});
