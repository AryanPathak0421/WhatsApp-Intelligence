/**
 * Google Drive import: reads exported chats from a Drive folder with the owner's own Google account (OAuth 2.0, authorization-code flow + PKCE).
 *
 *   phone: Export chat -> save to Drive "<root>/<Project name>/" ---> this service lists the folder, downloads new .txt/.zip files and imports them
 *
 * Least privilege: scope drive.readonly (it can list and download, it cannot change or delete anything in Drive). Nothing is moved or renamed in Drive;
 * what was handled is remembered in the DriveImport table (file id + md5), so a file is imported once and a replaced file (new md5) is imported again incrementally.
 * The refresh token is stored AES-256-GCM encrypted; the client secret only ever lives in the environment. This is the ONLY component that calls out to
 * the internet (googleapis.com / accounts.google.com), and only with the owner's consent; no chat text is ever sent to Google.
 */
import crypto from 'node:crypto';
import axios, { AxiosInstance } from 'axios';
import { config } from '../config';
import { prisma } from '../db';
import { JobQueue } from '../queues';
import { decryptField, encryptField } from '../utils/crypto';
import { MAX_EXPORT_BYTES, ingestExport } from './exportIngest';
import { listProjects } from './projectFolders';

export const DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive.readonly';
const FOLDER = 'application/vnd.google-apps.folder';
const EXPORT_NAME = /\.(txt|zip)$/i;
const MIN_AGE_MS = 20_000;                         // a file modified in the last seconds may still be uploading
const pending = new Map<string, { verifier: string; userId: string; expires: number }>();     // OAuth state -> PKCE verifier (single use, 10 min)

export const googleConfigured = () => Boolean(config().GOOGLE_CLIENT_ID && config().GOOGLE_CLIENT_SECRET);

const b64url = (b: Buffer) => b.toString('base64url');

export function buildAuthUrl(userId: string): string {
  const state = b64url(crypto.randomBytes(24));
  const verifier = b64url(crypto.randomBytes(48));
  const now = Date.now();
  for (const [k, v] of pending) if (v.expires < now) pending.delete(k);
  pending.set(state, { verifier, userId, expires: now + 10 * 60_000 });
  const q = new URLSearchParams({ client_id: config().GOOGLE_CLIENT_ID!, redirect_uri: config().GOOGLE_REDIRECT_URI, response_type: 'code', scope: DRIVE_SCOPE,
    access_type: 'offline', prompt: 'consent', include_granted_scopes: 'true', state, code_challenge: b64url(crypto.createHash('sha256').update(verifier).digest()), code_challenge_method: 'S256' });
  return `${config().GOOGLE_AUTH_URL}?${q}`;
}

/** Exchanges the code from Google's redirect; state must be one we issued (CSRF protection). Returns the user who started the flow. */
export async function completeAuth(code: string, state: string): Promise<{ userId: string; email?: string }> {
  const p = pending.get(state);
  pending.delete(state);
  if (!p || p.expires < Date.now()) throw new Error('This sign-in link expired or was not started here. Start again from Settings.');
  const r = await axios.post(config().GOOGLE_TOKEN_URL, new URLSearchParams({ code, client_id: config().GOOGLE_CLIENT_ID!, client_secret: config().GOOGLE_CLIENT_SECRET!,
    redirect_uri: config().GOOGLE_REDIRECT_URI, grant_type: 'authorization_code', code_verifier: p.verifier }), { timeout: 20_000 });
  const { access_token, refresh_token, scope, expires_in } = r.data as { access_token: string; refresh_token?: string; scope?: string; expires_in?: number };
  if (!refresh_token) throw new Error('Google did not return a refresh token. Remove the app from your Google account permissions and connect again.');
  if (!String(scope ?? '').includes('drive')) throw new Error('The Drive permission was not granted.');
  tokenCache = { token: access_token, until: Date.now() + (expires_in ?? 3600) * 1000 - 60_000 };
  let email: string | undefined;
  try { email = (await api(access_token).get('/drive/v3/about', { params: { fields: 'user(emailAddress)' } })).data?.user?.emailAddress; } catch { /* optional */ }
  await prisma.googleConnection.upsert({ where: { id: 'singleton' }, create: { connectedById: p.userId, accountEmail: email, refreshTokenEnc: encryptField(refresh_token), scope: scope ?? DRIVE_SCOPE },
    update: { connectedById: p.userId, accountEmail: email, refreshTokenEnc: encryptField(refresh_token), scope: scope ?? DRIVE_SCOPE, status: 'CONNECTED', lastError: null, connectedAt: new Date() } });
  return { userId: p.userId, email };
}

const api = (token: string): AxiosInstance => axios.create({ baseURL: config().GOOGLE_API_BASE, timeout: 60_000, headers: { Authorization: `Bearer ${token}` }, maxContentLength: MAX_EXPORT_BYTES, maxBodyLength: MAX_EXPORT_BYTES });
let tokenCache: { token: string; until: number } | null = null;

export class NeedsReauth extends Error {}

async function accessToken(): Promise<string> {
  if (tokenCache && tokenCache.until > Date.now()) return tokenCache.token;
  const c = await prisma.googleConnection.findUnique({ where: { id: 'singleton' } });
  if (!c) throw new Error('Google Drive is not connected');
  try {
    const r = await axios.post(config().GOOGLE_TOKEN_URL, new URLSearchParams({ client_id: config().GOOGLE_CLIENT_ID!, client_secret: config().GOOGLE_CLIENT_SECRET!,
      refresh_token: decryptField(c.refreshTokenEnc), grant_type: 'refresh_token' }), { timeout: 20_000 });
    tokenCache = { token: r.data.access_token, until: Date.now() + (r.data.expires_in ?? 3600) * 1000 - 60_000 };
    return tokenCache.token;
  } catch (e: any) {
    if (e?.response?.data?.error === 'invalid_grant') {          // revoked, or (apps in Testing status) the 7-day refresh-token lifetime ended
      await prisma.googleConnection.update({ where: { id: 'singleton' }, data: { status: 'NEEDS_REAUTH', lastError: 'Google rejected the saved sign-in. Connect again.' } });
      throw new NeedsReauth('Google rejected the saved sign-in');
    }
    throw e;
  }
}

const esc = (s: string) => s.replace(/\\/g, '\\\\').replace(/'/g, "\\'");

async function listAll(a: AxiosInstance, q: string, fields: string): Promise<any[]> {
  const out: any[] = [];
  let pageToken: string | undefined;
  do {
    const r = await a.get('/drive/v3/files', { params: { q, fields: `nextPageToken, files(${fields})`, pageSize: 200, pageToken, orderBy: 'name' } });
    out.push(...(r.data.files ?? []));
    pageToken = r.data.nextPageToken;
  } while (pageToken && out.length < 2000);
  return out;
}

export interface DriveEvent { at: string; folder?: string; file?: string; outcome: string; detail?: string }
const status = { running: false, lastRunAt: null as string | null, runs: 0, events: [] as DriveEvent[] };
const note = (e: Omit<DriveEvent, 'at'>) => { status.events.unshift({ at: new Date().toISOString(), ...e }); status.events.length = Math.min(status.events.length, 100); };

/** One pass: find the root folder, each project's sub-folder, and import files that are new or replaced. Returns the number of files handled. */
export async function syncOnce(queue: JobQueue): Promise<number> {
  const conn = await prisma.googleConnection.findUnique({ where: { id: 'singleton' } });
  if (!conn || conn.status !== 'CONNECTED' || !googleConfigured()) return 0;
  let handled = 0;
  try {
    const a = api(await accessToken());
    const rootName = config().GOOGLE_DRIVE_ROOT_FOLDER;
    const roots = /^[\w-]{20,}$/.test(rootName)
      ? [{ id: rootName, name: rootName }]
      : await listAll(a, `name='${esc(rootName)}' and mimeType='${FOLDER}' and trashed=false and 'root' in parents`, 'id,name');
    if (roots.length !== 1) {
      note({ outcome: roots.length ? 'ambiguous-root' : 'no-root-folder', detail: roots.length ? `${roots.length} folders named "${rootName}" in My Drive` : `create a folder named "${rootName}" in My Drive` });
      await prisma.googleConnection.update({ where: { id: 'singleton' }, data: { lastSyncAt: new Date(), lastError: roots.length ? 'More than one root folder has this name' : `Folder "${rootName}" not found in My Drive` } });
      return 0;
    }
    const { byFolder } = await listProjects();
    for (const folder of await listAll(a, `'${esc(roots[0].id)}' in parents and mimeType='${FOLDER}' and trashed=false`, 'id,name')) {
      const matches = byFolder.get(String(folder.name).replace(/[\\/:*?"<>|]/g, '_').replace(/[. ]+$/, '').trim().toLowerCase()) ?? [];
      const files = (await listAll(a, `'${esc(folder.id)}' in parents and trashed=false and mimeType!='${FOLDER}'`, 'id,name,size,md5Checksum,modifiedTime'))
        .filter((f) => EXPORT_NAME.test(f.name ?? ''));
      if (!files.length) continue;
      if (matches.length !== 1) { note({ folder: folder.name, outcome: matches.length ? 'ambiguous-folder' : 'unknown-folder', detail: matches.length ? 'several projects share this name' : 'no project has this name; files left untouched' }); continue; }
      for (const f of files) {
        const done = await prisma.driveImport.findUnique({ where: { fileId: f.id } });
        if (done && done.md5 === (f.md5Checksum ?? null) && done.outcome !== 'waiting') continue;                       // already handled, unchanged
        if (Date.now() - Date.parse(f.modifiedTime) < MIN_AGE_MS) continue;                                             // still being uploaded
        if (Number(f.size ?? 0) > MAX_EXPORT_BYTES) { await remember(f, matches[0].id, 'rejected', 'File is larger than 200 MB'); note({ folder: folder.name, file: f.name, outcome: 'rejected', detail: 'too large' }); handled++; continue; }
        const data = Buffer.from((await a.get(`/drive/v3/files/${f.id}`, { params: { alt: 'media' }, responseType: 'arraybuffer' })).data);
        const out = await ingestExport({ project: matches[0], fileName: f.name, data, queue, source: `google-drive:${folder.name}` });
        if (out.kind === 'waiting' || out.kind === 'skipped') { note({ folder: folder.name, file: f.name, outcome: out.kind, detail: out.detail }); continue; }   // not recorded: retried next pass
        await remember(f, matches[0].id, out.kind, out.detail);
        note({ folder: folder.name, file: f.name, outcome: out.kind, detail: out.detail });
        handled++;
      }
    }
    await prisma.googleConnection.update({ where: { id: 'singleton' }, data: { lastSyncAt: new Date(), lastError: null } });
  } catch (e: any) {
    const msg = e instanceof NeedsReauth ? e.message : e?.response?.status ? `Google Drive answered ${e.response.status}` : 'Could not reach Google Drive';
    note({ outcome: 'error', detail: msg });
    await prisma.googleConnection.update({ where: { id: 'singleton' }, data: { lastError: msg, lastSyncAt: new Date() } }).catch(() => undefined);
  }
  status.lastRunAt = new Date().toISOString();
  status.runs++;
  return handled;
}

const remember = (f: any, projectId: string, outcome: string, detail?: string) => prisma.driveImport.upsert({ where: { fileId: f.id },
  create: { fileId: f.id, projectId, fileName: String(f.name).slice(0, 200), md5: f.md5Checksum ?? null, modifiedTime: f.modifiedTime ?? null, outcome, detail: detail?.slice(0, 300) },
  update: { projectId, fileName: String(f.name).slice(0, 200), md5: f.md5Checksum ?? null, modifiedTime: f.modifiedTime ?? null, outcome, detail: detail?.slice(0, 300), importedAt: new Date() } });

export async function driveStatus() {
  const c = await prisma.googleConnection.findUnique({ where: { id: 'singleton' } });
  return { configured: googleConfigured(), connected: c?.status === 'CONNECTED', needsReauth: c?.status === 'NEEDS_REAUTH', account: c?.accountEmail ?? null, scope: c?.scope ?? null,
    rootFolder: config().GOOGLE_DRIVE_ROOT_FOLDER, pollMs: config().GOOGLE_DRIVE_POLL_MS, connectedAt: c?.connectedAt ?? null, lastSyncAt: c?.lastSyncAt ?? null, lastError: c?.lastError ?? null,
    recentImports: await prisma.driveImport.findMany({ orderBy: { importedAt: 'desc' }, take: 10, select: { fileName: true, projectId: true, outcome: true, detail: true, importedAt: true } }), recent: status.events.slice(0, 20) };
}

/** Forget the stored credential and tell Google to revoke it (best effort). */
export async function disconnect(): Promise<void> {
  const c = await prisma.googleConnection.findUnique({ where: { id: 'singleton' } });
  if (!c) return;
  try { await axios.post(config().GOOGLE_REVOKE_URL, new URLSearchParams({ token: decryptField(c.refreshTokenEnc) }), { timeout: 10_000 }); } catch { /* already invalid or unreachable */ }
  await prisma.googleConnection.delete({ where: { id: 'singleton' } });
  tokenCache = null;
}

export function startDriveSync(queue: JobQueue): () => void {
  if (!googleConfigured()) return () => undefined;
  const tick = async () => { if (status.running) return; status.running = true; try { await syncOnce(queue); } finally { status.running = false; } };
  const t = setInterval(tick, config().GOOGLE_DRIVE_POLL_MS);
  console.log(`[google-drive] sync every ${Math.round(config().GOOGLE_DRIVE_POLL_MS / 1000)} s once connected`);
  return () => clearInterval(t);
}

export const _test = { reset: () => { tokenCache = null; pending.clear(); status.events.length = 0; } };
