import clsx from 'clsx';
import { useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { Badge, Card, CardHeader, EmptyState, ErrorState, PageHeader, Select, Skeleton } from '../components/ui';
import { titleCase } from '../lib/format';
import { useQa, useSentiment, useSummaries } from '../lib/queries';

type Tab = 'questions' | 'sentiment' | 'summaries';
const TABS: { id: Tab; label: string }[] = [{ id: 'questions', label: 'Questions' }, { id: 'sentiment', label: 'Tone' }, { id: 'summaries', label: 'Summaries' }];
const STATUS_TONE: Record<string, 'green' | 'amber' | 'red' | 'gray'> = { ANSWERED: 'green', POSSIBLY_ANSWERED: 'amber', UNANSWERED: 'red' };
const fmtMin = (m?: number | null) => (m == null ? '—' : m < 60 ? `${Math.round(m)} min` : `${(m / 60).toFixed(1)} h`);
const day = (iso?: string) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : '');

const Stat = ({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) => (
  <Card className="px-5 py-4"><p className="muted text-xs">{label}</p><p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>{hint && <p className="muted mt-0.5 text-[11px]">{hint}</p>}</Card>
);

function Questions({ projectId }: { projectId: string }) {
  const [status, setStatus] = useState('');
  const { data, isLoading, error, refetch } = useQa(projectId, status || undefined);
  if (error) return <ErrorState error={error} onRetry={refetch} />;
  const s = data?.stats;
  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="Questions" value={isLoading ? '…' : s?.total_questions ?? 0} />
        <Stat label="Answered" value={isLoading ? '…' : s?.answered ?? 0} hint={s?.answer_rate != null ? `${Math.round(s.answer_rate * 100)}% of questions` : undefined} />
        <Stat label="Possibly answered" value={isLoading ? '…' : s?.possibly_answered ?? 0} hint="needs review, not counted as answered" />
        <Stat label="Unanswered" value={isLoading ? '…' : s?.unanswered ?? 0} hint={s?.client_questions_unanswered ? `${s.client_questions_unanswered} from the client` : undefined} />
        <Stat label="Median response" value={isLoading ? '…' : fmtMin(s?.median_response_minutes)} hint="answered questions only" />
      </div>
      <Card className="mt-5">
        <CardHeader title="Questions and answers" sub="An answer is only counted when a different person replied with matching content; weaker matches are flagged." right={
          <Select aria-label="Filter by status" className="w-44" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option><option value="ANSWERED">Answered</option><option value="POSSIBLY_ANSWERED">Possibly answered</option><option value="UNANSWERED">Unanswered</option>
          </Select>} />
        {isLoading ? <div className="p-5"><Skeleton className="h-40" /></div> : !data?.items.length ? <EmptyState title="No questions found" hint="Upload and analyse a chat first." /> : (
          <ul className="divide-y">{data.items.map((q: any) => (
            <li key={q.id} className="px-5 py-3.5">
              <div className="flex flex-wrap items-center gap-2"><Badge tone={STATUS_TONE[q.status] ?? 'gray'}>{titleCase(q.status)}</Badge>
                <span className="muted text-xs">{q.asked_by} · {day(q.asked_at)}{q.type ? ` · ${q.type}` : ''}</span>
                {q.status === 'ANSWERED' && <span className="muted text-xs">answered by {q.answered_by} in {fmtMin(q.response_minutes)}</span>}
                {q.age_hours != null && <span className="muted text-xs">waiting {q.age_hours >= 48 ? `${Math.round(q.age_hours / 24)} days` : `${Math.round(q.age_hours)} h`}</span>}
                {q.needs_review && <Badge tone="gray">Needs review</Badge>}</div>
              <p className="mt-1.5 text-sm">{q.text}</p>
              <p className="muted mt-1 text-xs">Based on {q.evidence_message_ids.length} message{q.evidence_message_ids.length === 1 ? '' : 's'}{q.reasons?.length ? ` · ${q.reasons.join(', ')}` : ''}</p>
            </li>))}</ul>)}
      </Card>
    </>
  );
}

function Sentiment({ projectId }: { projectId: string }) {
  const { data, isLoading, error, refetch } = useSentiment(projectId);
  if (error) return <ErrorState error={error} onRetry={refetch} />;
  const c = data?.counts;
  const total = c ? c.POSITIVE + c.NEUTRAL + c.NEGATIVE : 0;
  const pct = (n: number) => (total ? Math.round((100 * n) / total) : 0);
  return (
    <>
      <p className="muted mb-3 text-xs">Tone is estimated from word cues (English, Hinglish, Hindi). It is a signal to review, not a measurement; sarcasm is not detected.</p>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Positive" value={isLoading ? '…' : `${pct(c?.POSITIVE ?? 0)}%`} hint={`${c?.POSITIVE ?? 0} messages`} />
        <Stat label="Negative" value={isLoading ? '…' : `${pct(c?.NEGATIVE ?? 0)}%`} hint={`${c?.NEGATIVE ?? 0} messages`} />
        <Stat label="Frustrated" value={isLoading ? '…' : c?.frustrated ?? 0} />
        <Stat label="Urgent" value={isLoading ? '…' : c?.urgent ?? 0} />
      </div>
      <Card className="mt-5"><CardHeader title="Messages worth a look" sub="Most urgent, frustrated or strongly worded first. The cue words are shown so you can disagree." />
        {isLoading ? <div className="p-5"><Skeleton className="h-40" /></div> : !data?.items?.length ? <EmptyState title="Nothing notable" /> : (
          <ul className="divide-y">{data.items.slice(0, 40).map((m: any) => (
            <li key={m.message_id} className="px-5 py-3"><div className="flex flex-wrap items-center gap-2">
              <Badge tone={m.label === 'NEGATIVE' ? 'red' : m.label === 'POSITIVE' ? 'green' : 'gray'}>{titleCase(m.label)}</Badge>
              {m.frustration && <Badge tone="amber">Frustrated</Badge>}{m.urgency > 0 && <Badge tone="amber">Urgent</Badge>}
              <span className="muted text-xs">{m.sender ?? 'unknown'} · {day(m.ts)}</span></div>
              <p className="muted mt-1 text-xs">Cues: {m.evidence.join(', ') || '—'}</p></li>))}</ul>)}
      </Card>
    </>
  );
}

function Summaries({ projectId }: { projectId: string }) {
  const [kind, setKind] = useState<'daily' | 'weekly' | 'monthly'>('weekly');
  const { data, isLoading, error, refetch } = useSummaries(projectId, kind);
  if (error) return <ErrorState error={error} onRetry={refetch} />;
  return (
    <Card>
      <CardHeader title="Summaries" sub="Built from verified facts day by day, then merged into weeks and months. Every highlight links to its source messages." right={
        <div className="flex gap-1" role="tablist" aria-label="Period">{(['daily', 'weekly', 'monthly'] as const).map((k) => (
          <button key={k} role="tab" aria-selected={kind === k} onClick={() => setKind(k)} className={clsx('rounded-md px-2.5 py-1 text-xs', kind === k ? 'bg-brand-500/10 font-medium text-brand-700 dark:text-brand-100' : 'muted hover:bg-[var(--surface-2)]')}>{titleCase(k)}</button>))}</div>} />
      {isLoading ? <div className="p-5"><Skeleton className="h-40" /></div> : !data?.items.length ? <EmptyState title="No summaries yet" hint="Analyse a chat to generate them." /> : (
        <ul className="divide-y">{data.items.map((p: any) => (
          <li key={p.key} className="px-5 py-4"><div className="flex flex-wrap items-baseline gap-2"><h4 className="text-sm font-semibold">{p.key}</h4>
            <span className="muted text-xs">{p.stats.messages} messages · {p.stats.participants} participants</span></div>
            <p className="mt-1.5 whitespace-pre-line text-sm">{p.text}</p>
            {p.trend && <p className="muted mt-1 text-xs">vs previous month: messages {p.trend.messages_vs_previous_month_pct >= 0 ? '+' : ''}{p.trend.messages_vs_previous_month_pct}%, completed tasks {p.trend.tasks_completed_delta >= 0 ? '+' : ''}{p.trend.tasks_completed_delta}</p>}
            <p className="muted mt-1 text-xs">Evidence: {p.evidence_message_ids.length} message{p.evidence_message_ids.length === 1 ? '' : 's'}</p></li>))}</ul>)}
    </Card>
  );
}

export default function Insights() {
  const { projectId } = useOutletContext<{ projectId?: string }>();
  const [tab, setTab] = useState<Tab>('questions');
  if (!projectId) return <EmptyState title="Select a project first" />;
  return (
    <>
      <PageHeader title="Conversation insights" sub="Questions and answers, tone, and period summaries, each tied to the messages it came from." />
      <div className="mb-4 flex gap-1 border-b" role="tablist">{TABS.map((t) => (
        <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
          className={clsx('-mb-px border-b-2 px-3 py-2 text-sm', tab === t.id ? 'border-brand-600 font-medium' : 'muted border-transparent hover:text-[var(--text)]')}>{t.label}</button>))}</div>
      {tab === 'questions' && <Questions projectId={projectId} />}
      {tab === 'sentiment' && <Sentiment projectId={projectId} />}
      {tab === 'summaries' && <Summaries projectId={projectId} />}
    </>
  );
}
