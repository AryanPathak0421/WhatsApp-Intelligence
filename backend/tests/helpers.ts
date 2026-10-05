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

export const uploadChat = (ctx: Ctx, auth: Record<string, string>, projectId: string, text: string | Buffer, name = 'chat.txt') =>
  request(ctx.app).post(`/api/projects/${projectId}/chat/upload`).set(auth).attach('file', Buffer.from(text), name);

export async function waitJob(ctx: Ctx, auth: Record<string, string>, jobId: string) {
  await ctx.queue.idle();
  return (await request(ctx.app).get(`/api/analysis/${jobId}`).set(auth)).body;
}
