import os from 'node:os';
import path from 'node:path';

export const TEST_DB = process.env.TEST_DATABASE_URL ?? 'postgresql://wa:wa_dev_pw@localhost:15432/wa_intel_test';
export const AI_PORT = 18000;
export const TEST_ENV = {
  NODE_ENV: 'test',
  DATABASE_URL: TEST_DB,
  JWT_ACCESS_SECRET: 'test-access-secret-0123456789abcdef0123456789',
  JWT_REFRESH_SECRET: 'test-refresh-secret-0123456789abcdef012345678',
  FIELD_ENCRYPTION_KEY: '00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff',
  AI_ENGINE_URL: `http://127.0.0.1:${AI_PORT}`,
  AI_ENGINE_TOKEN: 'test-service-token',
  UPLOAD_DIR: path.join(os.tmpdir(), 'wa-intel-test-uploads'),
  QUEUE_MODE: 'inline',
  MAX_UPLOAD_BYTES: String(2 * 1024 * 1024),
  WHATSAPP_APP_SECRET: 'test-whatsapp-app-secret-0123456789',
  WHATSAPP_VERIFY_TOKEN: 'verify-token-12345',
  WEBHOOK_DEBOUNCE_MS: '150',
};
