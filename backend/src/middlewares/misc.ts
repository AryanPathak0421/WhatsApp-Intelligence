import { NextFunction, Request, Response } from 'express';
import multer from 'multer';
import { ZodType } from 'zod';
import { config } from '../config';
import { prisma } from '../db';
import { AppError } from '../utils/errors';

export const validateBody = <T>(schema: ZodType<T>) => (req: Request, _res: Response, next: NextFunction) => {
  const r = schema.safeParse(req.body);
  if (!r.success) return next(r.error);
  req.body = r.data;
  next();
};
export const validateQuery = <T>(schema: ZodType<T>) => (req: Request, _res: Response, next: NextFunction) => {
  const r = schema.safeParse(req.query);
  if (!r.success) return next(r.error);
  (req as unknown as { q: T }).q = r.data;
  next();
};

export async function audit(req: Request, action: string, opts: { entity?: string; entityId?: string; projectId?: string; meta?: unknown } = {}) {
  try {
    await prisma.auditLog.create({ data: { userId: req.user?.id, action, entity: opts.entity, entityId: opts.entityId,
      projectId: opts.projectId, ip: req.ip, meta: (opts.meta ?? undefined) as never } });
  } catch (e) { console.error('[audit] failed', (e as Error).message); } // never break the request because of logging
}

/** In-memory sliding-window limiter (per key). Fine for one node; use Redis for multi-node. */
export function rateLimiter(max: number, windowMs: number, keyFn: (req: Request) => string) {
  const hits = new Map<string, number[]>();
  return {
    check(req: Request) {
      const k = keyFn(req), now = Date.now();
      const arr = (hits.get(k) ?? []).filter((t) => now - t < windowMs);
      hits.set(k, arr);
      return arr.length < max;
    },
    fail(req: Request) { const k = keyFn(req); hits.set(k, [...(hits.get(k) ?? []), Date.now()]); },
    reset(req: Request) { hits.delete(keyFn(req)); },
  };
}

export const upload = () => multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: config().MAX_UPLOAD_BYTES, files: 1, fields: 5 },
  fileFilter: (_req, file, cb) => {
    const ok = /\.txt$/i.test(file.originalname);
    if (ok) return cb(null, true);
    (cb as unknown as (e: Error) => void)(new AppError(415, 'UNSUPPORTED_TYPE', 'Only .txt WhatsApp exports are supported'));
  },
});

export const pageParams = (q: { limit?: unknown; cursor?: unknown }) => ({
  limit: Math.min(Math.max(parseInt(String(q.limit ?? '50'), 10) || 50, 1), 200),
  cursor: typeof q.cursor === 'string' && q.cursor ? q.cursor : undefined,
});
