import { NextFunction, Request, Response } from 'express';
import { ZodError } from 'zod';
import { Prisma } from '@prisma/client';

export class AppError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
  }
}
export const notFound = (what = 'Resource') => new AppError(404, 'NOT_FOUND', `${what} not found`);
export const forbidden = (msg = 'You do not have permission to do that') => new AppError(403, 'FORBIDDEN', msg);
export const badRequest = (msg: string, details?: unknown) => new AppError(400, 'BAD_REQUEST', msg, details);

/** Never leaks stack traces or internals: unknown errors become a generic 500 (logged server-side). */
export function errorHandler(err: unknown, req: Request, res: Response, _next: NextFunction) {
  if (err instanceof AppError) {
    return res.status(err.status).json({ error: { code: err.code, message: err.message, details: err.details } });
  }
  if (err instanceof ZodError) {
    return res.status(422).json({ error: { code: 'VALIDATION_ERROR', message: 'Invalid input',
      details: err.issues.map((i) => ({ path: i.path.join('.'), message: i.message })) } });
  }
  if (err instanceof Prisma.PrismaClientKnownRequestError && err.code === 'P2025') {
    return res.status(404).json({ error: { code: 'NOT_FOUND', message: 'Resource not found' } });
  }
  if (err instanceof Prisma.PrismaClientInitializationError) {
    console.error('[db] unavailable', err.message);
    return res.status(503).json({ error: { code: 'DATABASE_UNAVAILABLE', message: 'Service temporarily unavailable' } });
  }
  if ((err as { type?: string })?.type === 'entity.parse.failed') {
    return res.status(400).json({ error: { code: 'BAD_JSON', message: 'Malformed JSON body' } });
  }
  console.error('[unhandled]', req.method, req.path, err); // stack stays in server logs only
  return res.status(500).json({ error: { code: 'INTERNAL_ERROR', message: 'Something went wrong' } });
}

export const asyncHandler =
  <T extends Request>(fn: (req: T, res: Response, next: NextFunction) => Promise<unknown>) =>
  (req: T, res: Response, next: NextFunction) => { fn(req, res, next).catch(next); };
