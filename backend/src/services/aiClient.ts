import axios, { AxiosError } from 'axios';
import { config } from '../config';

/** Error with a message that is safe to show to end users (no URLs, stack traces, or upstream bodies). */
export class AiError extends Error {
  constructor(public kind: 'UNAVAILABLE' | 'TIMEOUT' | 'INVALID_CHAT' | 'FAILED', public safeMessage: string) { super(safeMessage); }
}

function client() {
  return axios.create({
    baseURL: config().AI_ENGINE_URL, timeout: config().AI_TIMEOUT_MS, maxBodyLength: Infinity, maxContentLength: Infinity,
    headers: config().AI_ENGINE_TOKEN ? { 'x-service-token': config().AI_ENGINE_TOKEN } : {},
  });
}

function wrap(e: unknown): never {
  const err = e as AxiosError<{ detail?: unknown }>;
  if (err.code === 'ECONNABORTED' || err.code === 'ETIMEDOUT') throw new AiError('TIMEOUT', 'Analysis timed out');
  if (!err.response) throw new AiError('UNAVAILABLE', 'Analysis service is unavailable');
  if (err.response.status === 422) {
    const d = err.response.data?.detail;
    throw new AiError('INVALID_CHAT', typeof d === 'string' ? d : 'The chat file could not be understood');
  }
  throw new AiError('FAILED', 'Analysis failed');
}

export interface AiMessage {
  messageId: string; index: number; timestamp: string; senderName: string | null; senderPhone: string | null;
  message: string; rawText: string; messageType: string; isSystemMessage: boolean; isMedia: boolean; isDeleted: boolean;
  isEdited: boolean; isForwarded: boolean; urls: string[];
}
export interface ParseResult { fingerprint: string; messages: AiMessage[]; report: Record<string, unknown> }

export const ai = {
  async parse(buf: Buffer, filename = 'chat.txt'): Promise<ParseResult> {
    try {
      const fd = new FormData();
      fd.append('file', new Blob([new Uint8Array(buf)]), filename);
      return (await client().post('/ai/parse', fd)).data;
    } catch (e) { return wrap(e); }
  },
  async analyze(body: unknown): Promise<any> {
    try { return (await client().post('/ai/analyze-messages', body)).data; } catch (e) { return wrap(e); }
  },
  async report(body: unknown): Promise<any> {
    try { return (await client().post('/ai/report-messages', body)).data; } catch (e) { return wrap(e); }
  },
  async exportReport(report: unknown, format: string, section?: string): Promise<{ data: Buffer; type: string }> {
    try {
      const r = await client().post('/ai/export', { report, format, section: section ?? 'Tasks' }, { responseType: 'arraybuffer' });
      return { data: Buffer.from(r.data), type: String(r.headers['content-type']) };
    } catch (e) { return wrap(e); }
  },
  /** Liveness of the AI engine, used by readiness/status endpoints (short timeout, never throws). */
  async status(): Promise<{ reachable: boolean; model?: unknown }> {
    try {
      const c = axios.create({ baseURL: config().AI_ENGINE_URL, timeout: 2500, headers: config().AI_ENGINE_TOKEN ? { 'x-service-token': config().AI_ENGINE_TOKEN } : {} });
      await c.get('/health');
      const model = await c.get('/ai/model').then((r) => r.data).catch(() => undefined);
      return { reachable: true, model };
    } catch { return { reachable: false }; }
  },
  /** Drops the engine's in-memory search index for a project (retention / erasure). Never throws: an engine that is down has nothing indexed to leak. */
  async dropIndex(projectId: string): Promise<boolean> {
    try { return Boolean((await client().delete(`/ai/index/${encodeURIComponent(projectId)}`)).data?.dropped); } catch { return false; }
  },
  async index(projectId: string, messages: unknown[]): Promise<void> {
    try { await client().post('/ai/index', { project_id: projectId, messages }); } catch (e) { wrap(e); }
  },
  async search(body: unknown): Promise<any> {
    try { return (await client().post('/ai/search', body)).data; } catch (e) {
      if ((e as AxiosError).response?.status === 404) return null; // not indexed yet
      return wrap(e);
    }
  },
};
