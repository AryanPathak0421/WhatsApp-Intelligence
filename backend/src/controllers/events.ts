import { Router } from 'express';
import { prisma } from '../db';
import { authenticate } from '../middlewares/auth';
import { events, LiveEvent } from '../events/bus';
import { isAdmin } from '../utils/permissions';

const MAX_STREAMS_PER_USER = 5;
const HEARTBEAT_MS = 25_000;
const ACCESS_TTL_MS = 30_000;
const open = new Map<string, number>();

/** Server-sent events. Requires the normal bearer token (the frontend reads the stream with fetch, since EventSource cannot send headers). */
export const eventsRouter = Router();
eventsRouter.use(authenticate);

eventsRouter.get('/events', (req, res) => {
  const user = req.user!;
  if ((open.get(user.id) ?? 0) >= MAX_STREAMS_PER_USER) return void res.status(429).json({ error: { code: 'TOO_MANY_STREAMS', message: 'Too many open live connections' } });
  open.set(user.id, (open.get(user.id) ?? 0) + 1);

  res.status(200).set({ 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-cache, no-transform', Connection: 'keep-alive', 'X-Accel-Buffering': 'no' });
  res.write('retry: 5000\n: connected\n\n');

  const cache = new Map<string, { ok: boolean; at: number }>();
  const canSee = async (projectId: string) => {
    const hit = cache.get(projectId);
    if (hit && Date.now() - hit.at < ACCESS_TTL_MS) return hit.ok;       // short cache: membership changes apply within 30 s
    const ok = isAdmin(user.role) || Boolean(await prisma.projectMember.findFirst({ where: { projectId, userId: user.id, canView: true }, select: { id: true } }));
    cache.set(projectId, { ok, at: Date.now() });
    return ok;
  };

  let seq = 0;
  const off = events.subscribe(async (e: LiveEvent) => {
    try {
      if (e.userIds) { if (!e.userIds.includes(user.id)) return; }          // chat: room members only
      else if (!(await canSee(e.projectId))) return;
      res.write(`id: ${++seq}\nevent: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`);
    } catch { /* connection closing */ }
  });
  const beat = setInterval(() => res.write(': ping\n\n'), HEARTBEAT_MS);

  req.on('close', () => {
    clearInterval(beat);
    off();
    open.set(user.id, Math.max(0, (open.get(user.id) ?? 1) - 1));
  });
});
