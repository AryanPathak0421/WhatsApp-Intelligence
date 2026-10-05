import request from 'supertest';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { createApp } from '../src/app';
import { prisma } from '../src/db';
import { createQueue } from '../src/queues';
import { bootstrapAdmin, resetDb } from './helpers';

const lines: string[] = [];
const queue = createQueue();
const app = createApp(queue, (l) => lines.push(l));
beforeAll(resetDb);
afterAll(async () => { await queue.close(); await prisma.$disconnect(); });

describe('request logging', () => {
  it('writes one JSON line per request with no query string, body or token', async () => {
    const admin = await bootstrapAdmin({ app, queue });
    lines.length = 0;
    const r = await request(app).get('/api/projects?secretsearch=confidential-chat-text').set(admin.auth).set('x-request-id', 'trace-abc12345');
    expect(r.headers['x-request-id']).toBe('trace-abc12345');
    const rec = JSON.parse(lines.at(-1)!);
    expect(rec).toMatchObject({ method: 'GET', path: '/api/projects', status: 200, requestId: 'trace-abc12345', userId: admin.user.id });
    const all = lines.join('\n');
    expect(all).not.toContain('confidential-chat-text');
    expect(all).not.toContain(admin.token);
  });

  it('generates a request id, hides ids in paths, and skips health probes', async () => {
    lines.length = 0;
    await request(app).get('/health');
    expect(lines).toHaveLength(0);
    const r = await request(app).get('/api/projects/11111111-2222-3333-4444-555555555555/tasks').set('x-request-id', 'bad id!');
    expect(r.headers['x-request-id']).toMatch(/^[0-9a-f-]{36}$/);        // malformed incoming ids are replaced
    const rec = JSON.parse(lines.at(-1)!);
    expect(rec.path).toBe('/api/projects/:id/tasks');
    expect(rec.status).toBe(401);
  });
});
