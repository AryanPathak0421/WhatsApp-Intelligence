import crypto from 'node:crypto';
import http from 'node:http';
import request from 'supertest';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { prisma } from '../src/db';
import { _test as driveTest, syncOnce } from '../src/services/googleDrive';
import { bootstrapAdmin, createUser, makeCtx, resetDb, Session } from './helpers';

const PART1 = `[01/10/2026, 10:00 AM] Priya: Rahul, please integrate Razorpay by Friday.
[01/10/2026, 10:05 AM] Rahul: Working on it.
`;
const FULL = PART1 + `[02/10/2026, 12:00 PM] Priya: Started on the admin dashboard.
[02/10/2026, 12:30 PM] Rahul: Razorpay integration is done.
`;
const ago = (ms: number) => new Date(Date.now() - ms).toISOString();
const md5 = (b: string) => crypto.createHash('md5').update(b).digest('hex');

/** A stand-in for Google (OAuth + Drive v3 as far as this feature uses it). It records every request so the tests can assert on what was asked. */
const google = {
  server: null as http.Server | null,
  calls: [] as { method: string; path: string; auth?: string; body?: string; q?: string }[],
  files: { F1: [] as { id: string; name: string; content: string; modifiedTime: string }[], F2: [] as { id: string; name: string; content: string; modifiedTime: string }[] },
  refreshFails: false,
  rootCount: 1,
};

function startGoogle(): Promise<void> {
  google.server = http.createServer((req, res) => {
    const url = new URL(req.url!, 'http://x');
    let body = '';
    req.on('data', (c) => (body += c));
    req.on('end', () => {
      google.calls.push({ method: req.method!, path: url.pathname, auth: req.headers.authorization, body, q: url.searchParams.get('q') ?? undefined });
      const json = (code: number, o: unknown) => { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(o)); };
      if (url.pathname === '/token') {
        const f = new URLSearchParams(body);
        if (f.get('client_id') !== 'test-client-id.apps.googleusercontent.com' || f.get('client_secret') !== 'test-client-secret-0123456789') return json(401, { error: 'invalid_client' });
        if (f.get('grant_type') === 'authorization_code') {
          if (f.get('code') !== 'GOOD' || !f.get('code_verifier')) return json(400, { error: 'invalid_grant' });
          return json(200, { access_token: 'AT1', refresh_token: 'RT-secret-1', scope: 'https://www.googleapis.com/auth/drive.readonly', expires_in: 3600 });
        }
        if (google.refreshFails) return json(400, { error: 'invalid_grant' });
        return json(200, { access_token: 'AT2', expires_in: 3600 });
      }
      if (url.pathname === '/revoke') return json(200, {});
      if (!/^Bearer AT[12]$/.test(req.headers.authorization ?? '')) return json(401, { error: { code: 401 } });
      if (url.pathname === '/drive/v3/about') return json(200, { user: { emailAddress: 'owner@example.com' } });
      const media = url.pathname.match(/^\/drive\/v3\/files\/([\w-]+)$/);
      if (media && url.searchParams.get('alt') === 'media') {
        const f = [...google.files.F1, ...google.files.F2].find((x) => x.id === media[1]);
        if (!f) return json(404, {});
        res.writeHead(200, { 'Content-Type': 'application/octet-stream' });
        return void res.end(f.content);
      }
      if (url.pathname === '/drive/v3/files') {
        const q = url.searchParams.get('q') ?? '';
        const fileView = (x: { id: string; name: string; content: string; modifiedTime: string }) => ({ id: x.id, name: x.name, size: String(x.content.length), md5Checksum: md5(x.content), modifiedTime: x.modifiedTime });
        if (q.includes("name='WhatsApp Exports'")) return json(200, { files: Array.from({ length: google.rootCount }, (_, i) => ({ id: `ROOT${i}`, name: 'WhatsApp Exports' })) });
        if (q.includes("'ROOT0' in parents") && q.includes('folder')) return json(200, { files: [{ id: 'F1', name: 'Drive Project' }, { id: 'F2', name: 'Nobody Knows' }] });
        if (q.includes("'F1' in parents")) return json(200, { files: google.files.F1.map(fileView) });
        if (q.includes("'F2' in parents")) return json(200, { files: google.files.F2.map(fileView) });
        return json(200, { files: [] });
      }
      json(404, {});
    });
  });
  return new Promise((r) => google.server!.listen(19876, '127.0.0.1', r));
}

const ctx = makeCtx();
let admin: Session, pm: Session;
let pid: string;

beforeAll(async () => {
  await startGoogle();
  await resetDb();
  await prisma.googleConnection.deleteMany();
  await prisma.driveImport.deleteMany();
  admin = await bootstrapAdmin(ctx);
  pm = await createUser(ctx, admin, 'PROJECT_MANAGER', 'pm@example.com');
  pid = (await request(ctx.app).post('/api/projects').set(pm.auth).send({ name: 'Drive Project' })).body.id;
});
afterAll(async () => { await ctx.queue.idle(); await ctx.queue.close(); await prisma.$disconnect(); google.server?.close(); });

const asAdmin = (m: 'get' | 'post' | 'delete', url: string) => request(ctx.app)[m](url).set(admin.auth);

describe('connecting a Google account', () => {
  it('is admin-only and builds a PKCE authorization URL with the read-only Drive scope and no secret in it', async () => {
    expect((await request(ctx.app).post('/api/google/connect')).status).toBe(401);
    expect((await request(ctx.app).post('/api/google/connect').set(pm.auth)).status).toBe(403);
    const r = await asAdmin('post', '/api/google/connect');
    expect(r.status).toBe(200);
    const u = new URL(r.body.url);
    expect(u.origin + u.pathname).toBe('http://127.0.0.1:19876/auth');
    expect(u.searchParams.get('scope')).toBe('https://www.googleapis.com/auth/drive.readonly');
    expect(u.searchParams.get('code_challenge_method')).toBe('S256');
    expect(u.searchParams.get('access_type')).toBe('offline');
    expect(u.searchParams.get('state')!.length).toBeGreaterThan(20);
    expect(r.body.url).not.toContain('test-client-secret');
  });

  it('rejects a callback with an unknown state, a user denial, or no code, and stores nothing', async () => {
    for (const q of ['code=GOOD&state=forged', 'error=access_denied', 'state=x']) {
      const r = await request(ctx.app).get(`/api/google/callback?${q}`);
      expect(r.status).toBe(302);
      expect(r.headers.location).toContain('/settings?google=error');
    }
    expect(await prisma.googleConnection.count()).toBe(0);
  });

  it('completes the flow once, stores the refresh token encrypted, and the state cannot be replayed', async () => {
    const state = new URL((await asAdmin('post', '/api/google/connect')).body.url).searchParams.get('state')!;
    const ok = await request(ctx.app).get(`/api/google/callback?code=GOOD&state=${state}`);
    expect(ok.headers.location).toBe('http://localhost:5199/settings?google=connected');
    const row = await prisma.googleConnection.findUniqueOrThrow({ where: { id: 'singleton' } });
    expect(row.refreshTokenEnc.startsWith('enc1:')).toBe(true);
    expect(row.refreshTokenEnc).not.toContain('RT-secret-1');
    expect(row.accountEmail).toBe('owner@example.com');
    const again = await request(ctx.app).get(`/api/google/callback?code=GOOD&state=${state}`);
    expect(again.headers.location).toContain('google=error');
    const st = (await asAdmin('get', '/api/google/status')).body;
    expect(st).toMatchObject({ configured: true, connected: true, account: 'owner@example.com', rootFolder: 'WhatsApp Exports' });
    expect(JSON.stringify(st)).not.toMatch(/RT-secret|enc1:|client_secret|test-client-secret/);
    expect((await request(ctx.app).get('/api/google/status').set(pm.auth)).status).toBe(403);
  });
});

describe('syncing exports from Drive', () => {
  it('imports a stable export into the project whose name matches the folder, and only reads from Drive', async () => {
    google.files.F1 = [{ id: 'f-chat', name: 'WhatsApp Chat with Team.txt', content: PART1, modifiedTime: ago(3_600_000) },
                       { id: 'f-photo', name: 'photo.jpg', content: 'jpeg', modifiedTime: ago(3_600_000) }];
    google.files.F2 = [{ id: 'f-other', name: 'chat.txt', content: PART1, modifiedTime: ago(3_600_000) }];
    google.calls.length = 0;
    expect(await syncOnce(ctx.queue)).toBe(1);
    await ctx.queue.idle();
    expect(await prisma.chatMessage.count({ where: { projectId: pid } })).toBe(2);
    expect(await prisma.driveImport.findUniqueOrThrow({ where: { fileId: 'f-chat' } })).toMatchObject({ outcome: 'imported', projectId: pid });
    expect(await prisma.driveImport.count({ where: { fileId: 'f-photo' } })).toBe(0);                           // not an export
    expect(await prisma.driveImport.count({ where: { fileId: 'f-other' } })).toBe(0);                           // folder matches no project: untouched
    expect(google.calls.some((c) => c.path === '/drive/v3/files/f-other')).toBe(false);                         // and never even downloaded
    expect(google.calls.every((c) => c.method === 'GET' || c.path === '/token')).toBe(true);                    // read-only: no writes to Drive
    expect(google.calls.filter((c) => c.path.startsWith('/drive/')).every((c) => /^Bearer AT[12]$/.test(c.auth ?? ''))).toBe(true);
    const uploads = await prisma.chatUpload.findMany({ where: { projectId: pid } });
    expect(uploads).toHaveLength(1);
  });

  it('does not download an unchanged file again, but imports a replaced one incrementally', async () => {
    google.calls.length = 0;
    expect(await syncOnce(ctx.queue)).toBe(0);
    expect(google.calls.some((c) => c.path === '/drive/v3/files/f-chat')).toBe(false);
    google.files.F1[0] = { ...google.files.F1[0], content: FULL, modifiedTime: ago(3_000_000) };                // the phone exported the whole chat again
    expect(await syncOnce(ctx.queue)).toBe(1);
    await ctx.queue.idle();
    expect(await prisma.chatMessage.count({ where: { projectId: pid } })).toBe(4);                              // 2 old + 2 new, nothing duplicated
    expect((await prisma.driveImport.findUniqueOrThrow({ where: { fileId: 'f-chat' } })).md5).toBe(md5(FULL));
  });

  it('waits for a file that was modified a moment ago, and records rejected files so they are not retried forever', async () => {
    google.files.F1.push({ id: 'f-fresh', name: 'new export.txt', content: FULL + '[03/10/2026, 09:00 AM] Priya: please deploy on Monday\n', modifiedTime: ago(2_000) });
    google.files.F1.push({ id: 'f-junk', name: 'notes.txt', content: 'milk\neggs\n', modifiedTime: ago(3_600_000) });
    await syncOnce(ctx.queue);
    expect(await prisma.driveImport.count({ where: { fileId: 'f-fresh' } })).toBe(0);
    expect((await prisma.driveImport.findUniqueOrThrow({ where: { fileId: 'f-junk' } })).outcome).toBe('rejected');
    google.files.F1.find((f) => f.id === 'f-fresh')!.modifiedTime = ago(120_000);
    await syncOnce(ctx.queue);
    await ctx.queue.idle();
    expect(await prisma.chatMessage.count({ where: { projectId: pid } })).toBe(5);
  });

  it('reports a missing or ambiguous root folder without touching anything', async () => {
    google.rootCount = 2;
    expect(await syncOnce(ctx.queue)).toBe(0);
    expect((await asAdmin('get', '/api/google/status')).body.lastError).toMatch(/More than one/);
    google.rootCount = 1;
    await syncOnce(ctx.queue);
    expect((await asAdmin('get', '/api/google/status')).body.lastError).toBeNull();
  });

  it('marks the connection as needing sign-in again when Google rejects the saved token, and stops calling Drive', async () => {
    driveTest.reset();                                                                                          // forget the cached access token so a refresh is attempted
    google.refreshFails = true;
    google.calls.length = 0;
    await syncOnce(ctx.queue);
    const st = (await asAdmin('get', '/api/google/status')).body;
    expect(st).toMatchObject({ connected: false, needsReauth: true });
    expect(google.calls.some((c) => c.path.startsWith('/drive/'))).toBe(false);
    google.calls.length = 0;
    await syncOnce(ctx.queue);
    expect(google.calls.length).toBe(0);
    google.refreshFails = false;
  });
});

describe('disconnecting', () => {
  it('revokes the token at Google, deletes the stored credential, and stops syncing', async () => {
    google.calls.length = 0;
    expect((await request(ctx.app).delete('/api/google/connection').set(pm.auth)).status).toBe(403);
    expect((await asAdmin('delete', '/api/google/connection')).status).toBe(204);
    expect(google.calls.some((c) => c.path === '/revoke' && c.body?.includes('RT-secret-1'))).toBe(true);
    expect(await prisma.googleConnection.count()).toBe(0);
    expect((await asAdmin('get', '/api/google/status')).body).toMatchObject({ connected: false });
    expect(await syncOnce(ctx.queue)).toBe(0);
    expect(await prisma.auditLog.count({ where: { action: { in: ['CONNECT_GOOGLE_DRIVE', 'DISCONNECT_GOOGLE_DRIVE'] } } })).toBe(2);
  });
});
