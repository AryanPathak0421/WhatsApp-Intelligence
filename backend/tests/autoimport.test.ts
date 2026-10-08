import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import request from 'supertest';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { prisma } from '../src/db';
import { _resetForTests, folderNameFor, scaffoldFolders, scanOnce } from '../src/services/autoimport';
import { ZipError, extractFirstTxt } from '../src/utils/zipText';
import { makeZip } from './zip-util';
import { bootstrapAdmin, createUser, makeCtx, resetDb, Session } from './helpers';

const PART1 = `[01/10/2026, 10:00 AM] Priya: Rahul, please integrate Razorpay by Friday.
[01/10/2026, 10:05 AM] Rahul: Working on it.
`;
const FULL = PART1 + `[02/10/2026, 12:00 PM] Priya: Started on the admin dashboard.
[02/10/2026, 12:30 PM] Rahul: Razorpay integration is done.
`;

const ctx = makeCtx();
let admin: Session, pm: Session;
let root: string;
let pid: string;
const PNAME = 'Auto: Import? Project';          // characters that are illegal in Windows folder names

const put = (folder: string, name: string, data: Buffer | string) => fs.writeFile(path.join(root, folder, name), data);
const exists = (...p: string[]) => fs.stat(path.join(root, ...p)).then(() => true, () => false);
/** two scans: the first only records the file's size/mtime, the second imports it once it is stable */
const scan = async () => { await scanOnce(ctx.queue, root, 0); return scanOnce(ctx.queue, root, 0); };

beforeAll(async () => {
  await resetDb();
  root = await fs.mkdtemp(path.join(os.tmpdir(), 'wa-inbox-'));
  _resetForTests(root);
  admin = await bootstrapAdmin(ctx);
  pm = await createUser(ctx, admin, 'PROJECT_MANAGER', 'pm@example.com');
  pid = (await request(ctx.app).post('/api/projects').set(pm.auth).send({ name: PNAME })).body.id;
});
afterAll(async () => { await ctx.queue.idle(); await ctx.queue.close(); await prisma.$disconnect(); await fs.rm(root, { recursive: true, force: true }); });

describe('zip reader (pure)', () => {
  it('reads deflated and stored txt entries, skipping directories, __MACOSX and non-txt files', () => {
    const z = makeZip([{ name: '__MACOSX/._chat.txt', data: Buffer.from('x') }, { name: 'IMG-1.jpg', data: Buffer.from('jpeg') }, { name: 'WhatsApp Chat with X.txt', data: Buffer.from(PART1) }]);
    expect(extractFirstTxt(z, 1e6)).toMatchObject({ name: 'WhatsApp Chat with X.txt' });
    expect(extractFirstTxt(z, 1e6).data.toString()).toBe(PART1);
    expect(extractFirstTxt(makeZip([{ name: 'a.txt', data: Buffer.from(PART1), deflate: false }]), 1e6).data.toString()).toBe(PART1);
  });
  it('rejects garbage, missing txt, encrypted entries, and decompression bombs', () => {
    expect(() => extractFirstTxt(Buffer.from('not a zip at all'), 1e6)).toThrow(ZipError);
    expect(() => extractFirstTxt(makeZip([{ name: 'photo.jpg', data: Buffer.from('x') }]), 1e6)).toThrow(/No .txt/);
    expect(() => extractFirstTxt(makeZip([{ name: 'a.txt', data: Buffer.from(PART1), flags: 1 }]), 1e6)).toThrow(/Encrypted/);
    expect(() => extractFirstTxt(makeZip([{ name: 'a.txt', data: Buffer.alloc(5000, 'a') }]), 1000)).toThrow(/too large/);                     // declared size over the limit
    expect(() => extractFirstTxt(makeZip([{ name: 'a.txt', data: Buffer.alloc(5000, 'a'), claimSize: 10 }]), 1000)).toThrow(/size limit/);        // lies about its size
  });
});

describe('watched folder', () => {
  it('creates one folder per project with a Windows-safe name and a README, and is idempotent', async () => {
    expect(folderNameFor(PNAME)).toBe('Auto_ Import_ Project');
    const first = await scaffoldFolders(root);
    expect(first.created).toEqual(['Auto_ Import_ Project']);
    expect((await scaffoldFolders(root)).existing).toEqual(['Auto_ Import_ Project']);
    expect(await exists('README.txt')).toBe(true);
  });

  it('imports a stable .txt export once, moves it to imported/, and queues the analysis', async () => {
    await put('Auto_ Import_ Project', 'WhatsApp Chat with Team.txt', PART1);
    expect(await scanOnce(ctx.queue, root, 0)).toBe(0);                                            // first sight: not imported yet
    expect(await exists('Auto_ Import_ Project', 'WhatsApp Chat with Team.txt')).toBe(true);
    expect(await scanOnce(ctx.queue, root, 0)).toBe(1);
    expect(await exists('Auto_ Import_ Project', 'WhatsApp Chat with Team.txt')).toBe(false);
    expect((await fs.readdir(path.join(root, 'Auto_ Import_ Project', 'imported'))).length).toBe(1);
    await ctx.queue.idle();
    expect(await prisma.chatMessage.count({ where: { projectId: pid } })).toBe(2);
    expect(await prisma.auditLog.count({ where: { action: 'AUTO_IMPORT', projectId: pid } })).toBe(1);
  });

  it('the same file again is a duplicate (moved, nothing new stored); a longer export of the same chat adds only the new messages', async () => {
    await put('Auto_ Import_ Project', 'again.txt', PART1);
    await scan();
    expect(await prisma.chatUpload.count({ where: { projectId: pid } })).toBe(1);
    await put('Auto_ Import_ Project', 'longer export.txt', FULL);
    await scan();
    await ctx.queue.idle();
    expect(await prisma.chatMessage.count({ where: { projectId: pid } })).toBe(4);                  // 2 old + 2 new, no duplicates
    expect(await prisma.chatUpload.count({ where: { projectId: pid } })).toBe(2);
  });

  it('imports an Android-style .zip containing the chat', async () => {
    const more = FULL + `[03/10/2026, 09:00 AM] Priya: Great, please deploy on Monday.\n`;
    await put('Auto_ Import_ Project', 'WhatsApp Chat with Team.zip', makeZip([{ name: 'WhatsApp Chat with Team.txt', data: Buffer.from(more) }]));
    await scan();
    await ctx.queue.idle();
    expect(await prisma.chatMessage.count({ where: { projectId: pid } })).toBe(5);
  });

  it('rejects files that are not chats, with a reason file, and leaves unsupported names alone', async () => {
    await put('Auto_ Import_ Project', 'shopping list.txt', 'milk\neggs\nbread\n');
    await put('Auto_ Import_ Project', 'bad.zip', 'definitely not a zip');
    await put('Auto_ Import_ Project', 'photo.jpg', 'x');
    await put('Auto_ Import_ Project', '.hidden.txt', PART1);
    await scan();
    const rejected = await fs.readdir(path.join(root, 'Auto_ Import_ Project', 'rejected'));
    expect(rejected.filter((f) => f.endsWith('.reason.txt')).length).toBe(2);
    expect(await exists('Auto_ Import_ Project', 'photo.jpg')).toBe(true);
    expect(await exists('Auto_ Import_ Project', '.hidden.txt')).toBe(true);
  });

  it('never imports a file that is still changing', async () => {
    const f = 'growing.txt';
    await put('Auto_ Import_ Project', f, PART1);
    await scanOnce(ctx.queue, root, 0);
    await put('Auto_ Import_ Project', f, PART1 + '[05/10/2026, 10:00 AM] Priya: new line while syncing\n');       // size changed between scans
    expect(await scanOnce(ctx.queue, root, 0)).toBe(0);
    expect(await exists('Auto_ Import_ Project', f)).toBe(true);
    await scanOnce(ctx.queue, root, 0);                                                                           // now stable
    expect(await exists('Auto_ Import_ Project', f)).toBe(false);
    await ctx.queue.idle();
  });

  it('waits (does not lose the file) while an analysis is running for the project', async () => {
    await prisma.analysisJob.create({ data: { projectId: pid, status: 'RUNNING', stage: 'x', progress: 10 } });
    await put('Auto_ Import_ Project', 'while busy.txt', FULL + '[06/10/2026, 10:00 AM] Priya: one more\n');
    await scan();
    expect(await exists('Auto_ Import_ Project', 'while busy.txt')).toBe(true);
    await prisma.analysisJob.updateMany({ where: { projectId: pid, status: 'RUNNING' }, data: { status: 'COMPLETED' } });
    await scan();
    expect(await exists('Auto_ Import_ Project', 'while busy.txt')).toBe(false);
    await ctx.queue.idle();
  });

  it('reports unknown and ambiguous folders and does not touch their files', async () => {
    await fs.mkdir(path.join(root, 'No Such Project'), { recursive: true });
    await put('No Such Project', 'x.txt', PART1);
    const p2 = (await request(ctx.app).post('/api/projects').set(pm.auth).send({ name: 'Twin' })).body.id;
    await request(ctx.app).post('/api/projects').set(pm.auth).send({ name: 'Twin' });
    await fs.mkdir(path.join(root, 'Twin'), { recursive: true });
    await put('Twin', 'y.txt', PART1);
    await scan();
    expect(await exists('No Such Project', 'x.txt')).toBe(true);
    expect(await exists('Twin', 'y.txt')).toBe(true);
    expect(await prisma.chatUpload.count({ where: { projectId: p2 } })).toBe(0);
  });

  it('status is admin-only (disabled flag when no folder is configured in the test environment)', async () => {
    expect((await request(ctx.app).get('/api/auto-import/status')).status).toBe(401);
    expect((await request(ctx.app).get('/api/auto-import/status').set(pm.auth)).status).toBe(403);
    const s = await request(ctx.app).get('/api/auto-import/status').set(admin.auth);
    expect(s.status).toBe(200);
    expect(s.body).toHaveProperty('recent');
  });
});
