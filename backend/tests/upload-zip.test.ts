import request from 'supertest';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { prisma } from '../src/db';
import { makeZip } from './zip-util';
import { bootstrapAdmin, makeCtx, resetDb, Session, waitJob } from './helpers';

const CHAT = `[01/10/2026, 10:00 AM] Priya: Rahul, please integrate Razorpay by Friday.
[01/10/2026, 10:05 AM] Rahul: Working on it.
`;
const ctx = makeCtx();
let admin: Session;
let pid: string;
const send = (name: string, data: Buffer) => request(ctx.app).post(`/api/projects/${pid}/chat/upload`).set(admin.auth).attach('file', data, name);

beforeAll(async () => {
  await resetDb();
  admin = await bootstrapAdmin(ctx);
  pid = (await request(ctx.app).post('/api/projects').set(admin.auth).send({ name: 'Zip upload' })).body.id;
});
afterAll(async () => { await ctx.queue.idle(); await ctx.queue.close(); await prisma.$disconnect(); });

describe('uploading the .zip that WhatsApp creates', () => {
  it('reads the chat text out of the zip and analyses it like a .txt', async () => {
    const zip = makeZip([{ name: 'WhatsApp Chat with Team.txt', data: Buffer.from(CHAT) }, { name: 'IMG-0001.jpg', data: Buffer.from('jpeg bytes') }]);
    const r = await send('WhatsApp Chat with Team.zip', zip);
    expect(r.status).toBe(202);
    expect((await waitJob(ctx, admin.auth, r.body.jobId)).status).toBe('COMPLETED');
    expect(await prisma.chatMessage.count({ where: { projectId: pid } })).toBe(2);
    expect((await prisma.chatUpload.findFirstOrThrow({ where: { projectId: pid } })).fileName).toBe('WhatsApp Chat with Team.txt');
  });
  it('treats the same chat as a duplicate whether it arrives as .txt or .zip', async () => {
    const again = await send('chat.txt', Buffer.from(CHAT));
    expect(again.status).toBe(409);
    expect(again.body.error.code).toBe('DUPLICATE_UPLOAD');
  });
  it('rejects a zip without a chat, a corrupt zip, and other file types', async () => {
    expect((await send('photos.zip', makeZip([{ name: 'a.jpg', data: Buffer.from('x') }]))).status).toBe(422);
    expect((await send('broken.zip', Buffer.from('this is not a zip'))).status).toBe(422);
    expect((await send('notes.pdf', Buffer.from('%PDF'))).status).toBe(415);
  });
});
