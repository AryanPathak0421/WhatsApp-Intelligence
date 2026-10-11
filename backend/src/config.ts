import { z } from 'zod';

const schema = z.object({
  NODE_ENV: z.enum(['development', 'test', 'production']).default('development'),
  PORT: z.coerce.number().default(4000),
  DATABASE_URL: z.string().min(1),
  REDIS_URL: z.string().optional(),
  QUEUE_MODE: z.enum(['bullmq', 'inline']).optional(),
  JWT_ACCESS_SECRET: z.string().min(32, 'JWT_ACCESS_SECRET must be at least 32 chars'),
  JWT_REFRESH_SECRET: z.string().min(32, 'JWT_REFRESH_SECRET must be at least 32 chars'),
  JWT_ACCESS_TTL: z.string().default('15m'),
  JWT_REFRESH_TTL_DAYS: z.coerce.number().default(7),
  FIELD_ENCRYPTION_KEY: z.string().regex(/^[0-9a-fA-F]{64}$/, 'FIELD_ENCRYPTION_KEY must be 32 bytes hex (64 chars)'),
  AI_ENGINE_URL: z.string().default('http://localhost:8000'),
  AI_ENGINE_TOKEN: z.string().optional(),
  AI_TIMEOUT_MS: z.coerce.number().default(600_000),
  UPLOAD_DIR: z.string().default('./uploads'),                                 // only to erase files left by the former chat-export import
  CORS_ORIGIN: z.string().default('http://localhost:5173'),
  TRUST_PROXY: z.coerce.number().default(0),
  ANALYSIS_DEBOUNCE_MS: z.coerce.number().default(30_000),                     // in-app chat: wait for a quiet moment, then analyse once
  FRONTEND_URL: z.string().url().default('http://localhost:5199'),
  // outgoing e-mail (chat invitations). Disabled unless SMTP_HOST is set; e.g. Gmail: smtp.gmail.com, 465, secure, an app password.
  SMTP_HOST: z.string().min(1).optional(),
  SMTP_PORT: z.coerce.number().default(465),
  SMTP_SECURE: z.enum(['true', 'false']).default('true').transform((v) => v === 'true'),
  SMTP_USER: z.string().optional(),
  SMTP_PASS: z.string().optional(),
  SMTP_FROM: z.string().optional(),                                             // default: "Project Intelligence <SMTP_USER>"
  INVITE_TTL_DAYS: z.coerce.number().default(7),
});

export type Config = z.infer<typeof schema> & { queueMode: 'bullmq' | 'inline' };

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const parsed = schema.safeParse(env);
  if (!parsed.success) {
    const msg = parsed.error.issues.map((i) => `${i.path.join('.')}: ${i.message}`).join('; ');
    throw new Error(`Invalid configuration: ${msg}`); // names the variables, never prints their values
  }
  const c = parsed.data;
  return { ...c, queueMode: c.QUEUE_MODE ?? (c.REDIS_URL ? 'bullmq' : 'inline') };
}

let cached: Config | undefined;
export const config = (): Config => (cached ??= loadConfig());
export const resetConfigForTests = () => { cached = undefined; };
