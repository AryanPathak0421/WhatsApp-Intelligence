import { NextFunction, Request, Response } from 'express';
import jwt from 'jsonwebtoken';
import { UserRole } from '@prisma/client';
import { config } from '../config';
import { prisma } from '../db';
import { AppError, forbidden, notFound } from '../utils/errors';
import { Action, can, isAdmin } from '../utils/permissions';

export interface AuthUser { id: string; role: UserRole; email: string }
declare module 'express-serve-static-core' {
  interface Request { user?: AuthUser; access?: { canEdit: boolean; admin: boolean } }
}

export const signAccess = (u: { id: string; role: UserRole }) =>
  jwt.sign({ role: u.role }, config().JWT_ACCESS_SECRET, { subject: u.id, expiresIn: config().JWT_ACCESS_TTL as jwt.SignOptions['expiresIn'] });

export async function authenticate(req: Request, _res: Response, next: NextFunction) {
  try {
    const h = req.headers.authorization;
    if (!h?.startsWith('Bearer ')) throw new AppError(401, 'UNAUTHENTICATED', 'Authentication required');
    let payload: jwt.JwtPayload;
    try {
      payload = jwt.verify(h.slice(7), config().JWT_ACCESS_SECRET, { algorithms: ['HS256'] }) as jwt.JwtPayload;
    } catch {
      throw new AppError(401, 'INVALID_TOKEN', 'Invalid or expired token');
    }
    // role and active flag come from the DB, not the token, so demotion/deactivation is immediate
    const user = await prisma.user.findUnique({ where: { id: payload.sub! }, select: { id: true, role: true, email: true, isActive: true } });
    if (!user || !user.isActive) throw new AppError(401, 'INVALID_TOKEN', 'Invalid or expired token');
    req.user = { id: user.id, role: user.role, email: user.email };
    next();
  } catch (e) { next(e); }
}

export const requirePermission = (...actions: Action[]) => (req: Request, _res: Response, next: NextFunction) => {
  if (!req.user) return next(new AppError(401, 'UNAUTHENTICATED', 'Authentication required'));
  if (!actions.every((a) => can(req.user!.role, a))) return next(forbidden());
  next();
};

/** Project-level isolation. Non-members get 404 (existence is not leaked). */
export const projectAccess = (level: 'view' | 'edit' = 'view', param = 'id') =>
  async (req: Request, _res: Response, next: NextFunction) => {
    try {
      const projectId = req.params[param];
      const user = req.user!;
      if (isAdmin(user.role)) {
        if (!(await prisma.project.findUnique({ where: { id: projectId }, select: { id: true } }))) throw notFound('Project');
        req.access = { canEdit: true, admin: true };
        return next();
      }
      const m = await prisma.projectMember.findUnique({ where: { projectId_userId: { projectId, userId: user.id } } });
      if (!m || !m.canView) throw notFound('Project');
      if (level === 'edit' && !m.canEdit) throw forbidden('Read-only access to this project');
      req.access = { canEdit: m.canEdit, admin: false };
      next();
    } catch (e) { next(e); }
  };

/** Resolve a child entity to its project, then run the project check. */
export const viaEntity = (
  lookup: (id: string) => Promise<{ projectId: string } | null>, level: 'view' | 'edit', param = 'id',
) => async (req: Request, res: Response, next: NextFunction) => {
  try {
    const row = await lookup(req.params[param]);
    if (!row) throw notFound();
    req.params.__projectId = row.projectId;
    return projectAccess(level, '__projectId')(req, res, next);
  } catch (e) { next(e); }
};
