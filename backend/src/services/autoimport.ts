/**
 * Watched-folder import: the practical automation for normal (personal) WhatsApp.
 *
 *   phone: "Export chat" (without media) -> Google Drive folder  ->  Google Drive for desktop syncs it to this PC  ->  this watcher imports it
 *
 * Layout under AUTO_IMPORT_DIR (one sub-folder per project, named like the project):
 *   <root>/<Project name>/WhatsApp Chat with X.txt        <- drop (or sync) an export here, .txt or .zip
 *   <root>/<Project name>/imported/                        <- successfully handled files are moved here (duplicates included)
 *   <root>/<Project name>/rejected/                        <- files that are not a usable chat, with a .reason.txt next to each
 * Safety: only direct children of a project folder are read (no recursion, no path from file contents), a file is imported only after its size and
 * modification time were stable across two scans (a half-synced file is never imported), an identical file is never imported twice, a project is
 * never analysed twice at once (the file simply waits), and the import is incremental (the pipeline appends only new messages).
 * This reads files the owner placed there; it does not touch WhatsApp in any way.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import { config } from '../config';
import { prisma } from '../db';
import { JobQueue } from '../queues';
import { importChatBuffer } from './importer';
import { extractFirstTxt, ZipError } from '../utils/zipText';

const MAX_BYTES = 200 * 1024 * 1024;
const EXT = /\.(txt|zip)$/i;
const IGNORE = /^(\.|~\$|desktop\.ini$|thumbs\.db$)|\.(tmp|crdownload|part|gdoc|gsheet|lnk)$/i;

export interface AutoImportEvent { at: string; folder: string; file?: string; outcome: string; detail?: string }
const state = { enabled: false, root: '', lastScanAt: null as string | null, scans: 0, running: false, events: [] as AutoImportEvent[], seen: new Map<string, string>(), warned: new Set<string>() };

const record = (e: Omit<AutoImportEvent, 'at'>) => { state.events.unshift({ at: new Date().toISOString(), ...e }); state.events.length = Math.min(state.events.length, 100); };

/** Windows-safe folder name for a project (the characters \ / : * ? " < > | are not allowed in file names). */
export const folderNameFor = (projectName: string) => projectName.replace(/[\\/:*?"<>|]/g, '_').replace(/[. ]+$/, '').trim() || 'project';

async function listProjects() {
  const projects = await prisma.project.findMany({ select: { id: true, name: true, managerId: true }, orderBy: { createdAt: 'asc' } });
  const byFolder = new Map<string, typeof projects>();
  for (const p of projects) { const k = folderNameFor(p.name).toLowerCase(); byFolder.set(k, [...(byFolder.get(k) ?? []), p]); }
  return { projects, byFolder };
}

async function uploaderFor(managerId: string | null): Promise<string | null> {
  if (managerId) return managerId;
  return (await prisma.user.findFirst({ where: { role: { in: ['SUPER_ADMIN', 'ADMIN'] }, isActive: true }, orderBy: { createdAt: 'asc' }, select: { id: true } }))?.id ?? null;
}

async function move(dir: string, file: string, sub: 'imported' | 'rejected', reason?: string) {
  const target = path.join(dir, sub);
  await fs.mkdir(target, { recursive: true });
  const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, '');
  const dest = path.join(target, `${stamp}_${file}`);
  await fs.rename(path.join(dir, file), dest).catch(async () => { await fs.copyFile(path.join(dir, file), dest); await fs.rm(path.join(dir, file), { force: true }); });
  if (reason) await fs.writeFile(`${dest}.reason.txt`, reason + '\n', 'utf8');
}

/** One pass over the watched folder. Returns how many files were handled (imported, duplicate, rejected). */
export async function scanOnce(queue: JobQueue, root = state.root, settleMs = config().AUTO_IMPORT_SETTLE_MS): Promise<number> {
  let handled = 0;
  const { byFolder } = await listProjects();
  const entries = await fs.readdir(root, { withFileTypes: true }).catch(() => []);
  for (const dirent of entries) {
    if (!dirent.isDirectory() || IGNORE.test(dirent.name)) continue;
    const folder = dirent.name, dir = path.join(root, folder);
    const matches = byFolder.get(folder.toLowerCase()) ?? [];
    const files = (await fs.readdir(dir, { withFileTypes: true }).catch(() => [])).filter((f) => f.isFile() && EXT.test(f.name) && !IGNORE.test(f.name));
    if (!files.length) continue;
    if (matches.length !== 1) {
      const key = `${folder}:${matches.length}`;
      if (!state.warned.has(key)) { state.warned.add(key); record({ folder, outcome: matches.length ? 'ambiguous-folder' : 'unknown-folder', detail: matches.length ? `${matches.length} projects share this name; rename one, or use a unique name` : 'no project has this name; files are left untouched' }); }
      continue;
    }
    const project = matches[0];
    for (const f of files) {
      const full = path.join(dir, f.name);
      const st = await fs.stat(full).catch(() => null);
      if (!st) continue;
      const sig = `${st.size}:${st.mtimeMs}`;
      if (state.seen.get(full) !== sig) { state.seen.set(full, sig); continue; }   // first sight, or the file is still changing: look again next scan
      if (Date.now() - st.mtimeMs < settleMs) continue;                            // modified moments ago: a sync may still be writing it
      if (st.size === 0 || st.size > MAX_BYTES) { await move(dir, f.name, 'rejected', st.size ? 'File is larger than 200 MB' : 'File is empty'); record({ folder, file: f.name, outcome: 'rejected', detail: st.size ? 'too large' : 'empty' }); handled++; continue; }
      let buf: Buffer = await fs.readFile(full);
      let nameInside = f.name;
      if (/\.zip$/i.test(f.name)) {
        try { const x = extractFirstTxt(buf, MAX_BYTES); buf = x.data; nameInside = path.basename(x.name); }
        catch (e) { const why = e instanceof ZipError ? e.message : 'The ZIP could not be read'; await move(dir, f.name, 'rejected', why); record({ folder, file: f.name, outcome: 'rejected', detail: why }); handled++; continue; }
      }
      const userId = await uploaderFor(project.managerId);
      if (!userId) { record({ folder, file: f.name, outcome: 'skipped', detail: 'no active admin/manager to attribute the import to' }); continue; }
      const out = await importChatBuffer({ projectId: project.id, userId, buffer: buf, fileName: nameInside, queue, source: `watched-folder:${folder}` });
      if (out.status === 'busy') { record({ folder, file: f.name, outcome: 'waiting', detail: 'an analysis is running for this project; will retry' }); continue; }
      if (out.status === 'invalid') { await move(dir, f.name, 'rejected', out.reason); record({ folder, file: f.name, outcome: 'rejected', detail: out.reason }); }
      else { await move(dir, f.name, 'imported'); record({ folder, file: f.name, outcome: out.status === 'queued' ? 'imported' : 'duplicate', detail: out.status === 'queued' ? `analysis job ${out.jobId}` : 'identical file was already imported' }); }
      state.seen.delete(full);
      handled++;
    }
  }
  state.lastScanAt = new Date().toISOString();
  state.scans++;
  return handled;
}

/** Creates one folder per project (unique names only) plus a short README; safe to call repeatedly. */
export async function scaffoldFolders(root = state.root): Promise<{ created: string[]; existing: string[]; skipped: { project: string; reason: string }[] }> {
  const { projects, byFolder } = await listProjects();
  const out = { created: [] as string[], existing: [] as string[], skipped: [] as { project: string; reason: string }[] };
  await fs.mkdir(root, { recursive: true });
  for (const p of projects) {
    const name = folderNameFor(p.name);
    if ((byFolder.get(name.toLowerCase()) ?? []).length > 1) { out.skipped.push({ project: p.name, reason: 'another project has the same name' }); continue; }
    const dir = path.join(root, name);
    const had = await fs.stat(dir).then(() => true, () => false);
    await fs.mkdir(dir, { recursive: true });
    (had ? out.existing : out.created).push(name);
  }
  await fs.writeFile(path.join(root, 'README.txt'),
    'WhatsApp export inbox\n\nPut an exported chat (.txt or .zip, "without media") into the folder named like the project.\nIt is imported automatically (only new messages are added) and moved to <project>/imported/.\nFiles that are not a usable chat go to <project>/rejected/ with a .reason.txt.\nIn WhatsApp: open the group > group name > Export chat > Without media > save to Google Drive (this folder, via Drive for desktop).\n', 'utf8');
  return out;
}

export function autoImportStatus() {
  return { enabled: state.enabled, root: state.root || null, intervalMs: config().AUTO_IMPORT_INTERVAL_MS, settleMs: config().AUTO_IMPORT_SETTLE_MS, lastScanAt: state.lastScanAt, scans: state.scans, recent: state.events.slice(0, 30) };
}

export async function pendingByFolder(root = state.root) {
  const { byFolder } = await listProjects();
  const rows: { folder: string; project: string | null; status: 'ok' | 'unknown' | 'ambiguous'; waitingFiles: number }[] = [];
  for (const d of await fs.readdir(root, { withFileTypes: true }).catch(() => [])) {
    if (!d.isDirectory()) continue;
    const n = (await fs.readdir(path.join(root, d.name)).catch(() => [])).filter((x) => EXT.test(x) && !IGNORE.test(x)).length;
    const m = byFolder.get(d.name.toLowerCase()) ?? [];
    rows.push({ folder: d.name, project: m.length === 1 ? m[0].name : null, status: m.length === 1 ? 'ok' : m.length ? 'ambiguous' : 'unknown', waitingFiles: n });
  }
  return rows;
}

export function startAutoImport(queue: JobQueue): () => void {
  const root = config().AUTO_IMPORT_DIR;
  if (!root) return () => undefined;
  state.enabled = true;
  state.root = path.resolve(root);
  void scaffoldFolders(state.root).catch((e) => console.error('[auto-import] cannot prepare folder', e.message));
  const tick = async () => {
    if (state.running) return;
    state.running = true;
    try { await scanOnce(queue); } catch (e) { console.error('[auto-import]', (e as Error).message); } finally { state.running = false; }
  };
  const t = setInterval(tick, config().AUTO_IMPORT_INTERVAL_MS);
  console.log(`[auto-import] watching ${state.root}`);
  return () => clearInterval(t);
}

/** Test seam: forget remembered file signatures and events. */
export function _resetForTests(root: string) { state.root = root; state.enabled = true; state.seen.clear(); state.warned.clear(); state.events.length = 0; state.scans = 0; }
