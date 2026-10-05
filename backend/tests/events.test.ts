import http from 'node:http';
import { AddressInfo } from 'node:net';
import request from 'supertest';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { prisma } from '../src/db';
import { bootstrapAdmin, createUser, makeCtx, resetDb, Session, uploadChat, waitJob } from './helpers';

const CHAT = `[01/10/2026, 10:00 AM] Priya: Rahul, please build the login page by Friday
[01/10/2026, 10:30 AM] Rahul: login page is done
`;

const ctx = makeCtx();
const server = http.createServer(ctx.app);
let base = '';
let admin: Session, pm: Session, outsider: Session;
let pid: string;

interface Stream { events: { event: string; data: any }[]; close: () => void; status: number }

async function openStream(auth: Record<string, string>): Promise<Stream> {
  const ac = new AbortController();
  const res = await fetch(`${base}/api/events`, { headers: auth, signal: ac.signal });
  const out: Stream = { events: [], close: () => ac.abort(), status: res.status };
  if (!res.ok || !res.body) return out;
  (async () => {
    const reader = res.body!.getReader();
    const dec = new TextDecoder();
    let buf = '';
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        for (let i = buf.indexOf('\n\n'); i >= 0; i = buf.indexOf('\n\n')) {
          const block = buf.slice(0, i); buf = buf.slice(i + 2);
          const ev = /^event: (.+)$/m.exec(block)?.[1]; const data = /^data: (.+)$/m.exec(block)?.[1];
          if (ev && data) out.events.push({ event: ev, data: JSON.parse(data) });
        }
      }
    } catch { /* aborted */ }
  })();
  return out;
}

const until = async (cond: () => boolean, ms = 15_000) => { const end = Date.now() + ms; while (!cond() && Date.now() < end) await new Promise((r) => setTimeout(r, 50)); };

beforeAll(async () => {
  await resetDb();
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
  base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  admin = await bootstrapAdmin(ctx);
  pm = await createUser(ctx, admin, 'PROJECT_MANAGER', 'pm@example.com');
  outsider = await createUser(ctx, admin, 'PROJECT_MANAGER', 'other@example.com');
  pid = (await request(ctx.app).post('/api/projects').set(pm.auth).send({ name: 'Live' })).body.id;
});
afterAll(async () => { server.closeAllConnections(); server.close(); await ctx.queue.close(); await prisma.$disconnect(); });

describe('live events (SSE)', () => {
  it('requires authentication', async () => {
    expect((await fetch(`${base}/api/events`)).status).toBe(401);
  });

  it('delivers job progress and completion to members only', async () => {
    const mine = await openStream(pm.auth);
    const admins = await openStream(admin.auth);
    const other = await openStream(outsider.auth);
    expect(mine.status).toBe(200);
    const up = await uploadChat(ctx, pm.auth, pid, CHAT);
    await waitJob(ctx, pm.auth, up.body.jobId);
    await until(() => mine.events.some((e) => e.event === 'analysis.completed'));
    await until(() => admins.events.some((e) => e.event === 'analysis.completed'));
    const done = mine.events.find((e) => e.event === 'analysis.completed')!;
    expect(done.data.projectId).toBe(pid);
    expect(done.data.progress).toBe(100);
    expect(mine.events.some((e) => e.event === 'analysis.progress')).toBe(true);
    expect(admins.events.some((e) => e.event === 'analysis.completed')).toBe(true);          // admins see every project
    expect(other.events.length).toBe(0);                                                       // a non-member receives nothing about it
    expect(JSON.stringify(mine.events)).not.toMatch(/login page|Priya|Rahul/);                // ids and numbers only, never message text
    [mine, admins, other].forEach((s) => s.close());
  });

  it('limits the number of simultaneous streams per user', async () => {
    const open: Stream[] = [];
    for (let i = 0; i < 5; i++) open.push(await openStream(pm.auth));
    expect(open.every((s) => s.status === 200)).toBe(true);
    expect((await openStream(pm.auth)).status).toBe(429);
    open.forEach((s) => s.close());
  });
});
