import { useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { CheckCircle2, FileUp, Loader2, Search, XCircle } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Input, PageHeader, ProgressBar, Select, Skeleton, useToast } from '../components/ui';
import { api, apiError } from '../lib/api';
import { useAuth } from '../lib/auth';
import { fmtDate, fmtDateTime, fmtTime } from '../lib/format';
import { useInvalidateProject, useJob, useMessages, useTeam, useUploads } from '../lib/queries';

const STEPS = ['Uploading', 'Parsing', 'Processing messages', 'Identifying team', 'Analyzing project', 'Indexing messages', 'Calculating progress', 'Generating report', 'Completed'];

function JobProgress({ jobId, onDone }: { jobId: string; onDone: () => void }) {
  const { data } = useJob(jobId);
  const done = useRef(false);
  useEffect(() => { if (data && ['COMPLETED', 'FAILED'].includes(data.status) && !done.current) { done.current = true; onDone(); } }, [data, onDone]);
  if (!data) return <Skeleton className="h-24" />;
  const idx = Math.max(0, STEPS.indexOf(data.stage ?? ''));
  const failed = data.status === 'FAILED';
  return (
    <div className="space-y-3" aria-live="polite">
      <div className="flex items-center justify-between text-sm"><span className="flex items-center gap-2 font-medium">
        {failed ? <XCircle className="size-4 text-red-500" /> : data.status === 'COMPLETED' ? <CheckCircle2 className="size-4 text-emerald-500" /> : <Loader2 className="size-4 animate-spin text-brand-500" />}
        {failed ? 'Analysis failed' : data.status === 'COMPLETED' ? 'Analysis complete' : `${data.stage ?? 'Queued'}…`}</span><span className="tabular-nums muted">{data.progress}%</span></div>
      <ProgressBar value={data.progress} tone={failed ? 'red' : data.status === 'COMPLETED' ? 'green' : 'brand'} label="Analysis progress" />
      {failed ? <p role="alert" className="text-sm text-red-600 dark:text-red-400">{data.error}</p> : (
        <ol className="flex flex-wrap gap-1.5">{STEPS.map((s, i) => <li key={s}><Badge tone={i < idx || data.status === 'COMPLETED' ? 'green' : i === idx ? 'blue' : 'gray'}>{s}</Badge></li>)}</ol>)}
    </div>
  );
}

function Uploader({ projectId }: { projectId: string }) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dup, setDup] = useState('');
  const input = useRef<HTMLInputElement>(null);
  const toast = useToast();
  const invalidate = useInvalidateProject();
  const { data: uploads } = useUploads(projectId);
  const hasData = !!uploads?.some((u) => u.status === 'COMPLETED');

  const send = useCallback(async (file: File) => {
    setDup(''); setBusy(true);
    const fd = new FormData(); fd.append('file', file);
    try { const r = await api.post(`/projects/${projectId}/chat/upload`, fd); setJobId(r.data.jobId); }
    catch (e) {
      const err = apiError(e);
      if (err.code === 'DUPLICATE_UPLOAD') setDup(err.message); else toast.push('error', err.message);
    } finally { setBusy(false); }
  }, [projectId, toast]);

  return (
    <Card>
      <CardHeader title={hasData ? 'Add a newer export' : 'Upload a WhatsApp chat'} sub={hasData ? 'Only new messages are added; tasks are never duplicated and your corrections are kept.' : 'Export the group chat from WhatsApp (without media) and drop the .txt file here.'} />
      <div className="space-y-4 px-5 pb-5">
        {!jobId ? (
          <div role="button" tabIndex={0} aria-label="Upload chat file" onClick={() => input.current?.click()} onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && input.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) send(f); }}
            className={clsx('flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors', over ? 'border-brand-500 bg-brand-500/5' : 'hover:bg-[var(--surface-2)]')}>
            {busy ? <Loader2 className="size-6 animate-spin text-brand-500" /> : <FileUp className="size-6 text-brand-500" />}
            <p className="text-sm font-medium">{busy ? 'Uploading…' : 'Drop your WhatsApp .txt export here, or click to browse'}</p>
            <p className="muted text-xs">Max 200 MB · stored encrypted · processed on your own servers</p>
            <input ref={input} type="file" accept=".txt,text/plain" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) send(f); e.target.value = ''; }} />
          </div>
        ) : <JobProgress jobId={jobId} onDone={() => { invalidate(projectId); toast.push('info', 'Analysis finished'); }} />}
        {dup && <div role="alert" className="rounded-lg bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-300">{dup}</div>}
        {jobId && <Button size="sm" onClick={() => { setJobId(null); }}>Upload another</Button>}
      </div>
    </Card>
  );
}

function Explorer({ projectId }: { projectId: string }) {
  const [q, setQ] = useState(''); const [applied, setApplied] = useState(''); const [sender, setSender] = useState(''); const [from, setFrom] = useState(''); const [to, setTo] = useState('');
  const [mode, setMode] = useState<'keyword' | 'semantic'>('keyword');
  const [extra, setExtra] = useState<any[]>([]); const [cursor, setCursor] = useState<string | undefined>();
  const [hits, setHits] = useState<any[] | null>(null);
  const qc = useQueryClient();
  const params: Record<string, string> = {};
  if (mode === 'keyword' && applied) params.q = applied;
  if (sender) params.sender = sender; if (from) params.from = new Date(from).toISOString(); if (to) params.to = new Date(to + 'T23:59:59Z').toISOString();
  if (cursor) params.cursor = cursor;
  const { data, isLoading, error, refetch, isFetching } = useMessages(projectId, params);
  const { data: team } = useTeam(projectId);
  useEffect(() => { setExtra([]); setCursor(undefined); }, [applied, sender, from, to, mode, projectId]);
  const items = [...extra, ...(data?.items ?? [])];
  const loadMore = () => { if (data?.nextCursor) { setExtra(items); setCursor(data.nextCursor); } };

  const run = async () => {
    setApplied(q);
    if (mode === 'semantic' && q) {
      try { setHits((await api.get(`/projects/${projectId}/search`, { params: { q } })).data.hits); } catch (e) { setHits([]); console.error(apiError(e)); }
    } else setHits(null);
    qc.invalidateQueries({ queryKey: ['messages'] });
  };
  return (
    <Card>
      <CardHeader title="Chat explorer" sub="Original messages, exactly as exported" />
      <div className="flex flex-wrap items-end gap-2 px-5 pb-3">
        <div className="relative min-w-52 flex-1"><Search className="muted pointer-events-none absolute left-3 top-2.5 size-4" />
          <Input aria-label="Search messages" className="pl-9" placeholder={mode === 'semantic' ? 'Ask: what happened with payment integration?' : 'Search messages…'} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && run()} /></div>
        <Select aria-label="Search mode" className="w-32" value={mode} onChange={(e) => { setMode(e.target.value as any); setHits(null); }}><option value="keyword">Keyword</option><option value="semantic">Semantic</option></Select>
        <Select aria-label="Filter by person" className="w-40" value={sender} onChange={(e) => setSender(e.target.value)}><option value="">Everyone</option>{team?.map((p) => <option key={p.id} value={p.name}>{p.name}</option>)}</Select>
        <Input aria-label="From date" type="date" className="w-36" value={from} onChange={(e) => setFrom(e.target.value)} /><Input aria-label="To date" type="date" className="w-36" value={to} onChange={(e) => setTo(e.target.value)} />
        <Button variant="primary" onClick={run}>Search</Button>
      </div>
      <div className="max-h-[560px] overflow-y-auto border-t">
        {mode === 'semantic' && hits ? (!hits.length ? <EmptyState title="No semantic matches" /> : (
          <ul className="divide-y">{hits.map((h) => <li key={h.message_id} className="px-5 py-3"><div className="mb-0.5 flex items-center gap-2 text-xs"><b>{h.sender}</b><span className="muted">{fmtDateTime(h.ts)}</span><Badge tone="blue">score {h.score}</Badge></div>
            <p className="text-sm">{h.text}</p>{h.context.length > 0 && <p className="muted mt-1 text-xs">{h.context.map((c: any) => `${c.sender}: ${c.text}`).join(' · ')}</p>}</li>)}</ul>
        )) : isLoading ? <div className="space-y-3 p-5">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-10" />)}</div>
          : error ? <ErrorState error={error} onRetry={refetch} /> : !items.length ? <EmptyState title="No messages found" hint="Try different filters, or upload a chat first." /> : (
            <ul>{items.map((m, i) => (
              <li key={m.id}>{(i === 0 || fmtDate(items[i - 1].timestamp) !== fmtDate(m.timestamp)) && <div className="sticky top-0 bg-[var(--surface-2)] px-5 py-1 text-[11px] font-medium muted">{fmtDate(m.timestamp)}</div>}
                <div className="flex gap-3 px-5 py-2 hover:bg-[var(--surface-2)]/50"><span className="muted w-12 shrink-0 pt-0.5 text-xs tabular-nums">{fmtTime(m.timestamp)}</span>
                  <div className="min-w-0"><p className="text-xs font-semibold">{m.sender?.name ?? 'System'}{m.isEdited && <span className="muted ml-1 font-normal">(edited)</span>}</p>
                    <p className={clsx('whitespace-pre-wrap break-words text-sm', (m.isDeleted || m.isMedia) && 'muted italic')}>{m.text || m.originalText}</p></div></div></li>))}</ul>)}
        {data?.nextCursor && <div className="border-t p-3 text-center"><Button size="sm" loading={isFetching} onClick={loadMore}>Load more</Button></div>}
      </div>
    </Card>
  );
}

export default function ChatAnalysis() {
  const { projectId } = useOutletContext<{ projectId?: string }>();
  const { can } = useAuth();
  const { data: uploads } = useUploads(projectId);
  if (!projectId) return <EmptyState title="Select a project first" />;
  return (
    <>
      <PageHeader title="Chat analysis" sub="Upload exports, then explore the original messages behind every insight." />
      <div className="grid gap-5">
        {can('chat:upload') && <Uploader projectId={projectId} />}
        {!!uploads?.length && <Card><CardHeader title="Imports" /><ul className="divide-y">{uploads.map((u) => (
          <li key={u.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-2.5 text-sm"><span className="font-medium">{u.fileName}</span><Badge tone={u.status === 'COMPLETED' ? 'green' : u.status === 'FAILED' ? 'red' : 'blue'}>{u.status.toLowerCase()}</Badge>
            <span className="muted text-xs">{u.messageCount} messages · {u.newMessageCount} new · {fmtDate(u.firstMessageAt)} – {fmtDate(u.lastMessageAt)}</span>{u.errorMessage && <span className="text-xs text-red-500">{u.errorMessage}</span>}</li>))}</ul></Card>}
        <Explorer projectId={projectId} />
      </div>
    </>
  );
}
