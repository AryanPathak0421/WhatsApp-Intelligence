import bcrypt from 'bcryptjs';
import { Router } from 'express';
import { z } from 'zod';
import { config } from '../config';
import { prisma } from '../db';
import { audit, rateLimiter, validateBody } from '../middlewares/misc';
import { authenticate, signAccess } from '../middlewares/auth';
import { AppError, asyncHandler, forbidden } from '../utils/errors';
import { randomToken, sha256 } from '../utils/crypto';
import { can } from '../utils/permissions';

export const authRouter = Router();
const loginLimit = rateLimiter(8, 15 * 60_000, (req) => `${req.ip}|${String(req.body?.email ?? '').toLowerCase()}`);
const DUMMY_HASH = bcrypt.hashSync('not-a-real-password', 10); // equalises timing for unknown users

const credentials = z.object({ email: z.string().email().toLowerCase(), password: z.string().min(1).max(200) });
const registerBody = z.object({
  email: z.string().email().toLowerCase(), name: z.string().min(1).max(100),
  password: z.string().min(10, 'Password must be at least 10 characters').max(200),
  role: z.enum(['SUPER_ADMIN', 'ADMIN', 'PROJECT_MANAGER', 'TEAM_MEMBER', 'SALES', 'CLIENT_VIEWER']).optional(),
});

async function issueTokens(user: { id: string; role: any }, req: any) {
  const refresh = randomToken();
  await prisma.refreshToken.create({ data: { userId: user.id, tokenHash: sha256(refresh),
    expiresAt: new Date(Date.now() + config().JWT_REFRESH_TTL_DAYS * 86_400_000) } });
  return { accessToken: signAccess(user), refreshToken: refresh, tokenType: 'Bearer' };
}
const publicUser = (u: { id: string; email: string; name: string; role: string }) => ({ id: u.id, email: u.email, name: u.name, role: u.role });

authRouter.post('/login', validateBody(credentials), asyncHandler(async (req, res) => {
  if (!loginLimit.check(req)) throw new AppError(429, 'TOO_MANY_ATTEMPTS', 'Too many failed attempts. Try again later.');
  const user = await prisma.user.findUnique({ where: { email: req.body.email } });
  const ok = await bcrypt.compare(req.body.password, user?.passwordHash ?? DUMMY_HASH);
  if (!user || !ok || !user.isActive) {
    loginLimit.fail(req);
    throw new AppError(401, 'INVALID_CREDENTIALS', 'Invalid email or password'); // same message for every failure
  }
  loginLimit.reset(req);
  await prisma.user.update({ where: { id: user.id }, data: { lastLoginAt: new Date() } });
  req.user = { id: user.id, role: user.role, email: user.email };
  await audit(req, 'LOGIN');
  res.json({ user: publicUser(user), ...(await issueTokens(user, req)) });
}));

/** First account bootstraps a SUPER_ADMIN. After that only admins can create users. */
authRouter.post('/register', validateBody(registerBody), asyncHandler(async (req, res, next) => {
  const count = await prisma.user.count();
  let role = req.body.role ?? 'TEAM_MEMBER';
  if (count === 0) role = 'SUPER_ADMIN';
  else {
    await new Promise<void>((resolve, reject) => authenticate(req, res, (e?: unknown) => (e ? reject(e) : resolve())));
    if (!can(req.user!.role, 'user:manage')) throw forbidden();
    if (role === 'SUPER_ADMIN' && req.user!.role !== 'SUPER_ADMIN') throw forbidden('Only a super admin can create super admins');
  }
  if (await prisma.user.findUnique({ where: { email: req.body.email } })) throw new AppError(409, 'EMAIL_TAKEN', 'An account with this email already exists');
  const user = await prisma.user.create({ data: { email: req.body.email, name: req.body.name, role, passwordHash: await bcrypt.hash(req.body.password, 12) } });
  await audit(req, 'CREATE_USER', { entity: 'User', entityId: user.id, meta: { role } });
  res.status(201).json({ user: publicUser(user) });
}));

/** Refresh-token rotation: each token works once; reuse of a spent token revokes the whole family (theft signal). */
authRouter.post('/refresh', validateBody(z.object({ refreshToken: z.string().min(10) })), asyncHandler(async (req, res) => {
  const row = await prisma.refreshToken.findUnique({ where: { tokenHash: sha256(req.body.refreshToken) }, include: { user: true } });
  if (!row || row.expiresAt < new Date() || !row.user.isActive) throw new AppError(401, 'INVALID_TOKEN', 'Invalid or expired token');
  if (row.revokedAt) {
    await prisma.refreshToken.updateMany({ where: { userId: row.userId, revokedAt: null }, data: { revokedAt: new Date() } });
    throw new AppError(401, 'INVALID_TOKEN', 'Invalid or expired token');
  }
  await prisma.refreshToken.update({ where: { id: row.id }, data: { revokedAt: new Date() } });
  res.json(await issueTokens(row.user, req));
}));

authRouter.post('/logout', validateBody(z.object({ refreshToken: z.string().min(10) })), asyncHandler(async (req, res) => {
  await prisma.refreshToken.updateMany({ where: { tokenHash: sha256(req.body.refreshToken), revokedAt: null }, data: { revokedAt: new Date() } });
  res.status(204).end();
}));

authRouter.get('/me', authenticate, asyncHandler(async (req, res) => {
  const u = await prisma.user.findUniqueOrThrow({ where: { id: req.user!.id } });
  res.json({ user: publicUser(u) });
}));
