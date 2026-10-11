import { useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { CheckCircle2, Loader2, MessagesSquare, RefreshCw, Search, XCircle } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useOutletContext } from 'react-router-dom';
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Input, PageHeader, ProgressBar, Select, Skeleton, useToast } from '../components/ui';
import { api, apiError } from '../lib/api';
import { useAuth } from '../lib/auth';
import { fmtDate, fmtDateTime, fmtTime } from '../lib/format';
import { useInvalidateProject, useJob, useMessages, useTeam } from '../lib/queries';

const STEPS = ['Queued', 'Starting', 'Identifying team', 'Analyzing project', 'Indexing messages', 'Calculating progress', 'Generating report', 'Completed'];

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

/** The conversation comes from the project's groups in Team chat; analysis runs automatically after new messages. This card shows the last run and lets editors re-run it. */
function Analyzer({ projectId }: { projectId: string }) {
  const { can } = useAuth();
  const toast = useToast();
  const invalidate = useInvalidateProject();
  const [jobId, setJobId] = useState<string | null>(null);
  const last = useQuery({ queryKey: ['last-analysis', projectId], queryFn: () => api.get(`/projects/${projectId}/chat/analysis`).then((r) => r.data as { id: string; status: string; finishedAt: string | null } | null) });
  const onDone = useCallback(() => { invalidate(projectId); void last.refetch(); }, [invalidate, projectId, last]);
  const run = async () => {
    try { const r = await api.post(`/projects/${projectId}/chat/reanalyze`); setJobId(r.data.jobId); }
    catch (e) { const err = apiError(e); if (err.code === 'ANALYSIS_IN_PROGRESS') setJobId((err.details as any)?.jobId ?? null); else toast.push('error', err.message); }
  };
  return (
    <Card>
      <CardHeader title="Analysis" sub="Messages from this project's groups in Team chat are analysed automatically shortly after the conversation goes quiet."
        right={<div className="flex gap-2"><Link to="/chat"><Button size="sm"><MessagesSquare className="size-4" />Open Team chat</Button></Link>
          {can('chat:upload') && <Button size="sm" variant="primary" onClick={() => void run()}><RefreshCw className="size-4" />Re-analyse now</Button>}</div>} />
      <div className="px-5 pb-5">
        {jobId ? <JobProgress jobId={jobId} onDone={onDone} />
          : <p className="muted text-sm">{last.data ? `Last analysis: ${last.data.status.toLowerCase()}${last.data.finishedAt ? ` · ${fmtDateTime(last.data.finishedAt)}` : ''}` : 'Not analysed yet.'}</p>}
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
      <CardHeader title="Message explorer" sub="The original messages behind every insight, exactly as written" />
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
          : error ? <ErrorState error={error} onRetry={refetch} /> : !items.length ? <EmptyState title="No messages found" hint="Try different filters, or start the conversation in Team chat." /> : (
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
  if (!projectId) return <EmptyState title="Select a project first" />;
  return (
    <>
      <PageHeader title="Chat analysis" sub="Explore the project's conversation and the messages behind every insight." />
      <div className="grid gap-5">
        <Analyzer projectId={projectId} />
        <Explorer projectId={projectId} />
      </div>
    </>
  );
}
