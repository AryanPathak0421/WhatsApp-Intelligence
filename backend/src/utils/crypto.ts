import crypto from 'node:crypto';
import { config } from '../config';

const key = () => Buffer.from(config().FIELD_ENCRYPTION_KEY, 'hex');

/** AES-256-GCM: output = iv(12) | tag(16) | ciphertext. Used for uploaded chat files at rest. */
export function encryptBuffer(plain: Buffer): Buffer {
  const iv = crypto.randomBytes(12);
  const c = crypto.createCipheriv('aes-256-gcm', key(), iv);
  const enc = Buffer.concat([c.update(plain), c.final()]);
  return Buffer.concat([iv, c.getAuthTag(), enc]);
}

export function decryptBuffer(blob: Buffer): Buffer {
  const d = crypto.createDecipheriv('aes-256-gcm', key(), blob.subarray(0, 12));
  d.setAuthTag(blob.subarray(12, 28));
  return Buffer.concat([d.update(blob.subarray(28)), d.final()]);
}

export const encryptField = (s: string) => 'enc1:' + encryptBuffer(Buffer.from(s, 'utf8')).toString('base64');
export const decryptField = (s: string) =>
  s.startsWith('enc1:') ? decryptBuffer(Buffer.from(s.slice(5), 'base64')).toString('utf8') : s;

/** Phone numbers are never shown in full unless the caller is allowed to see sensitive data. */
export function maskPhone(p?: string | null): string | null {
  if (!p) return null;
  const digits = p.replace(/[^\d+]/g, '');
  return digits.length <= 4 ? '••••' : `${digits.slice(0, 3)}${'•'.repeat(Math.max(3, digits.length - 7))}${digits.slice(-4)}`;
}

export const sha256 = (b: Buffer | string) => crypto.createHash('sha256').update(b).digest('hex');
export const randomToken = () => crypto.randomBytes(48).toString('base64url');
