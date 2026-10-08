import { Router } from 'express';
import { config } from '../config';
import { prisma } from '../db';
import { authenticate, requirePermission } from '../middlewares/auth';
import { audit } from '../middlewares/misc';
import { JobQueue } from '../queues';
import { buildAuthUrl, completeAuth, disconnect, driveStatus, googleConfigured, syncOnce } from '../services/googleDrive';
import { AppError, asyncHandler } from '../utils/errors';

/**
 * Google Drive connection (admin only). The OAuth redirect (/google/callback) is a browser navigation, so it carries no bearer token; it is protected by the
 * one-time `state` issued to a logged-in admin (CSRF) and a PKCE verifier. It redirects back to the frontend Settings page and never prints tokens.
 */
export function googleRouter(queue: JobQueue) {
  const r = Router();
  const need = [authenticate, requirePermission('user:manage')];

  r.get('/google/status', ...need, asyncHandler(async (_req, res) => res.json(await driveStatus())));

  r.post('/google/connect', ...need, asyncHandler(async (req, res) => {
    if (!googleConfigured()) throw new AppError(409, 'GOOGLE_NOT_CONFIGURED', 'Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in the backend environment first');
    res.json({ url: buildAuthUrl(req.user!.id) });
  }));

  r.get('/google/callback', asyncHandler(async (req, res) => {
    const back = (q: string) => res.redirect(`${config().FRONTEND_URL}/settings?${q}`);
    if (!googleConfigured()) return back('google=error&reason=not_configured');
    if (req.query.error) return back(`google=error&reason=${encodeURIComponent(String(req.query.error).slice(0, 40))}`);      // e.g. access_denied
    const code = String(req.query.code ?? ''), state = String(req.query.state ?? '');
    if (!code || !state) return back('google=error&reason=missing_code');
    try {
      const out = await completeAuth(code, state);
      await prisma.auditLog.create({ data: { userId: out.userId, action: 'CONNECT_GOOGLE_DRIVE', entity: 'GoogleConnection', entityId: 'singleton', meta: { account: out.email ?? null } } }).catch(() => undefined);
      return back('google=connected');
    } catch (e) {
      return back(`google=error&reason=${encodeURIComponent((e as Error).message.slice(0, 120))}`);
    }
  }));

  r.post('/google/sync', ...need, asyncHandler(async (_req, res) => res.json({ handled: await syncOnce(queue), status: await driveStatus() })));

  r.delete('/google/connection', ...need, asyncHandler(async (req, res) => {
    await disconnect();
    await audit(req, 'DISCONNECT_GOOGLE_DRIVE', { entity: 'GoogleConnection', entityId: 'singleton' });
    res.status(204).end();
  }));
  return r;
}
