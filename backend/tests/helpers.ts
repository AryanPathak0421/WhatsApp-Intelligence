import crypto from 'node:crypto';
import request from 'supertest';
import { createApp } from '../src/app';
import { prisma } from '../src/db';
import { createQueue, JobQueue } from '../src/queues';

export interface Ctx { app: ReturnType<typeof createApp>; queue: JobQueue }
export const makeCtx = (): Ctx => { const queue = createQueue(); return { app: createApp(queue), queue }; };

export async function resetDb() {
  // truncating users/projects cascades to everything owned by them
  await prisma.$executeRawUnsafe('TRUNCATE "User", "Project", "Client", "ModelVersion", "TrainingExample", "AuditLog" RESTART IDENTITY CASCADE');
}

export interface Session { token: string; refresh: string; user: { id: string; role: string; email: string }; auth: Record<string, string> }

export async function login(ctx: Ctx, email: string, password: string): Promise<Session> {
  const r = await request(ctx.app).post('/api/auth/login').send({ email, password });
  if (r.status !== 200) throw new Error('login failed ' + JSON.stringify(r.body));
  return { token: r.body.accessToken, refresh: r.body.refreshToken, user: r.body.user, auth: { Authorization: `Bearer ${r.body.accessToken}` } };
}

export async function bootstrapAdmin(ctx: Ctx, email = 'admin@example.com') {
  const r = await request(ctx.app).post('/api/auth/register').send({ email, name: 'Admin', password: 'correct-horse-battery' });
  if (r.status !== 201) throw new Error('bootstrap failed ' + JSON.stringify(r.body));
  return login(ctx, email, 'correct-horse-battery');
}

export async function createUser(ctx: Ctx, admin: Session, role: string, email: string) {
  const r = await request(ctx.app).post('/api/auth/register').set(admin.auth).send({ email, name: email.split('@')[0], password: 'correct-horse-battery', role });
  if (r.status !== 201) throw new Error('createUser failed ' + JSON.stringify(r.body));
  return login(ctx, email, 'correct-horse-battery');
}

/**
 * Seeds a project's conversation the way the in-app chat stores it (participants + ChatMessage rows on the in-app carrier upload),
 * then asks for a re-analysis. Fixtures are written as "[dd/mm/yyyy, h:mm AM] Name: text" lines; re-seeding the same lines adds nothing.
 * Returns { status, body: { jobId } } like the HTTP call, so tests read naturally.
 */
export async function seedChat(ctx: Ctx, auth: Record<string, string>, projectId: string, text: string) {
  const line = /^\[(\d{2})\/(\d{2})\/(\d{4}), (\d{1,2}):(\d{2}) (AM|PM)\] ([^:]+): ([\s\S]*)$/;
  const msgs: { ts: Date; sender: string; text: string }[] = [];
  for (const raw of text.split('\n')) {
    const m = line.exec(raw);
    if (m) {
      const h = (Number(m[4]) % 12) + (m[6] === 'PM' ? 12 : 0);
      msgs.push({ ts: new Date(Date.UTC(Number(m[3]), Number(m[2]) - 1, Number(m[1]), h, Number(m[5]))), sender: m[7].trim(), text: m[8] });
    } else if (raw.trim() && msgs.length) msgs[msgs.length - 1].text += '\n' + raw;     // continuation line
  }
  const user = await prisma.user.findFirstOrThrow({ orderBy: { createdAt: 'asc' } });
  const sha = (x: string) => crypto.createHash('sha256').update(x).digest('hex');
  const carrierSha = sha(`inapp:${projectId}`);
  const upload = await prisma.chatUpload.upsert({ where: { projectId_sha256: { projectId, sha256: carrierSha } }, update: {},
    create: { projectId, uploadedById: user.id, fileName: 'In-app chat', storageKey: 'inapp', sha256: carrierSha, sizeBytes: 0, status: 'COMPLETED' } });
  const seen = new Map<string, number>();
  let seq = ((await prisma.chatMessage.aggregate({ where: { projectId }, _max: { seq: true } }))._max.seq ?? -1) + 1;
  for (const m of msgs) {
    const key = `${m.ts.toISOString()}|${m.sender}|${m.text}`;
    const n = (seen.get(key) ?? 0) + 1; seen.set(key, n);
    const id = `${projectId}:seed_${sha(`${key}|${n}`).slice(0, 24)}`;
    if (await prisma.chatMessage.findUnique({ where: { id }, select: { id: true } })) continue;
    const p = await prisma.chatParticipant.upsert({ where: { projectId_displayName: { projectId, displayName: m.sender } }, update: {}, create: { projectId, displayName: m.sender } });
    await prisma.chatMessage.create({ data: { id, projectId, uploadId: upload.id, seq: seq++, senderId: p.id, timestamp: m.ts, originalText: m.text, text: m.text,
      urls: m.text.match(/https?:\/\/\S+/g) ?? [] } });
  }
  const r = await request(ctx.app).post(`/api/projects/${projectId}/chat/reanalyze`).set(auth);
  return { status: r.status, body: r.body };
}

export async function waitJob(ctx: Ctx, auth: Record<string, string>, jobId: string) {
  await ctx.queue.idle();
  return (await request(ctx.app).get(`/api/analysis/${jobId}`).set(auth)).body;
}
