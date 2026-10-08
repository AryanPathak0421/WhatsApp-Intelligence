import path from 'node:path';
import { JobQueue } from '../queues';
import { extractFirstTxt, ZipError } from '../utils/zipText';
import { importChatBuffer } from './importer';
import { ProjectRef, uploaderFor } from './projectFolders';

export const MAX_EXPORT_BYTES = 200 * 1024 * 1024;

export type IngestOutcome =
  | { kind: 'imported'; detail: string }
  | { kind: 'duplicate'; detail: string }
  | { kind: 'rejected'; detail: string }
  | { kind: 'waiting'; detail: string }       // not lost: try again later (an analysis is running)
  | { kind: 'skipped'; detail: string };      // cannot be attributed to a user right now

/**
 * One exported chat file (.txt or .zip, already in memory) -> import into a project. Shared by the watched folder and the Google Drive sync,
 * so both apply exactly the same rules: size cap, ZIP extraction with a decompression cap, WhatsApp-header check, duplicate refusal, one analysis at a time.
 */
export async function ingestExport(o: { project: ProjectRef; fileName: string; data: Buffer; queue: JobQueue; source: string }): Promise<IngestOutcome> {
  if (!o.data.length) return { kind: 'rejected', detail: 'File is empty' };
  if (o.data.length > MAX_EXPORT_BYTES) return { kind: 'rejected', detail: 'File is larger than 200 MB' };
  let buf: Buffer = o.data;
  let nameInside = o.fileName;
  if (/\.zip$/i.test(o.fileName)) {
    try { const x = extractFirstTxt(buf, MAX_EXPORT_BYTES); buf = x.data; nameInside = path.basename(x.name); }
    catch (e) { return { kind: 'rejected', detail: e instanceof ZipError ? e.message : 'The ZIP could not be read' }; }
  }
  const userId = await uploaderFor(o.project.managerId);
  if (!userId) return { kind: 'skipped', detail: 'no active admin/manager to attribute the import to' };
  const out = await importChatBuffer({ projectId: o.project.id, userId, buffer: buf, fileName: nameInside, queue: o.queue, source: o.source });
  if (out.status === 'busy') return { kind: 'waiting', detail: 'an analysis is running for this project; will retry' };
  if (out.status === 'invalid') return { kind: 'rejected', detail: out.reason };
  return out.status === 'queued' ? { kind: 'imported', detail: `analysis job ${out.jobId}` } : { kind: 'duplicate', detail: 'identical file was already imported' };
}
