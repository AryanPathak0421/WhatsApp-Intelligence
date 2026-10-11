/**
 * Outgoing e-mail over SMTP (chat invitations and "you were added" notices).
 * Disabled unless SMTP_HOST is set: then nothing is sent and callers are told so. Sending never throws into a request; failures are logged
 * without the message body or any token. The app password lives only in the environment (dev: private-data/dev.env, git-ignored).
 */
import nodemailer, { Transporter } from 'nodemailer';
import { config } from '../config';

let transport: Transporter | null | undefined;
export const sentForTests: { to: string; subject: string; text: string; html: string }[] = [];

export function _setTransportForTests(t: Transporter | null): void { transport = t; sentForTests.length = 0; }

function getTransport(): Transporter | null {
  if (transport !== undefined) return transport;
  const c = config();
  if (!c.SMTP_HOST) return (transport = null);
  transport = nodemailer.createTransport({
    host: c.SMTP_HOST, port: c.SMTP_PORT, secure: c.SMTP_SECURE,
    auth: c.SMTP_USER ? { user: c.SMTP_USER, pass: (c.SMTP_PASS ?? '').replace(/\s+/g, '') } : undefined,   // Gmail shows app passwords with spaces
    connectionTimeout: 15_000, greetingTimeout: 15_000, socketTimeout: 30_000,
  });
  return transport;
}

export const mailEnabled = () => getTransport() !== null;

export const escapeHtml = (s: string) => s.replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]!));

export async function sendMail(to: string, subject: string, text: string, html: string): Promise<boolean> {
  const t = getTransport();
  if (!t) { console.warn('[mail] SMTP not configured; not sent:', subject); return false; }
  const c = config();
  try {
    await t.sendMail({ from: c.SMTP_FROM || `Project Intelligence <${c.SMTP_USER}>`, to, subject, text, html });
    if (c.NODE_ENV === 'test') sentForTests.push({ to, subject, text, html });
    return true;
  } catch (e) {
    console.error('[mail] send failed:', (e as Error).message);                  // no body, no token
    return false;
  }
}

/** One simple, client-safe layout. Every user-provided string must already be escaped by the caller. */
export function layout(title: string, bodyHtml: string, button?: { label: string; url: string }): string {
  return `<!doctype html><html><body style="margin:0;background:#f0f2f5;font-family:Segoe UI,Helvetica,Arial,sans-serif;color:#111b21">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:32px 12px">
<table role="presentation" width="100%" style="max-width:520px;background:#ffffff;border-radius:12px;overflow:hidden">
<tr><td style="background:#00a884;color:#ffffff;padding:18px 24px;font-size:18px;font-weight:600">${title}</td></tr>
<tr><td style="padding:24px;font-size:15px;line-height:1.55">${bodyHtml}
${button ? `<p style="margin:28px 0 8px"><a href="${escapeHtml(button.url)}" style="background:#00a884;color:#ffffff;text-decoration:none;padding:12px 22px;border-radius:24px;font-weight:600;display:inline-block">${escapeHtml(button.label)}</a></p>
<p style="font-size:12px;color:#667781;word-break:break-all">Or open this link: ${escapeHtml(button.url)}</p>` : ''}
</td></tr>
<tr><td style="padding:14px 24px;font-size:12px;color:#667781;border-top:1px solid #e9edef">Sent by Project Intelligence. If you did not expect this e-mail, you can ignore it.</td></tr>
</table></td></tr></table></body></html>`;
}
