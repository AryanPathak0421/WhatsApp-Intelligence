import crypto from 'node:crypto';
import { NextFunction, Request, Response } from 'express';

/**
 * One JSON line per request on stdout. Deliberately logs NO query string, headers or bodies:
 * search text and chat content must never end up in log files. Correlate with the audit log via requestId.
 */
export function requestLog(write: (line: string) => void = (l) => process.stdout.write(l + '\n')) {
  return (req: Request, res: Response, next: NextFunction) => {
    const incoming = req.headers['x-request-id'];
    const requestId = typeof incoming === 'string' && /^[\w-]{8,64}$/.test(incoming) ? incoming : crypto.randomUUID();
    res.setHeader('X-Request-Id', requestId);
    const start = process.hrtime.bigint();
    const fullPath = req.originalUrl.split('?')[0];   // req.path is relative to the router mount point by the time 'finish' fires
    res.on('finish', () => {
      if (fullPath === '/health') return; // health probes would drown the log
      write(JSON.stringify({ t: new Date().toISOString(), requestId, method: req.method, path: fullPath.replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, ':id'),
        status: res.statusCode, ms: Math.round(Number(process.hrtime.bigint() - start) / 1e6), userId: req.user?.id ?? null }));
    });
    next();
  };
}
