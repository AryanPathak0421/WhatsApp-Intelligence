import { AlertTriangle, Swords } from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import { Badge, Card, CardHeader, EmptyState, ErrorState, PageHeader, ProgressBar, SeverityBadge, Skeleton, StatusBadge } from '../components/ui';
import { titleCase } from '../lib/format';
import { useConflicts, useRisks } from '../lib/queries';

export default function Risks() {
  const { projectId } = useOutletContext<{ projectId?: string }>();
  const { data, isLoading, error, refetch } = useRisks(projectId);
  const conflicts = useConflicts(projectId);
  if (!projectId) return <EmptyState title="Select a project first" />;
  if (error) return <ErrorState error={error} onRetry={refetch} />;
  const s = data?.summary;
  return (
    <>
      <PageHeader title="Risks & conflicts" sub="Each risk shows why it was raised and which messages it is based on." />
      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-1"><CardHeader title="Risk score" sub="Weighted factors, 0–100" />
          <div className="space-y-4 px-5 pb-5">{isLoading ? <Skeleton className="h-40" /> : !s ? <EmptyState title="Not analysed yet" /> : <>
            <div className="flex items-end gap-3"><span className="text-4xl font-semibold tabular-nums">{s.score}</span><SeverityBadge severity={s.level} /></div>
            <ul className="space-y-2.5">{Object.entries<any>(s.factors).map(([k, f]) => (
              <li key={k}><div className="flex justify-between text-xs"><span>{titleCase(k)}</span><span className="muted tabular-nums">+{f.contribution}</span></div><ProgressBar value={f.value * 100} tone={f.value > 0.6 ? 'red' : f.value > 0.3 ? 'amber' : 'brand'} /></li>))}</ul></>}</div>
        </Card>
        <Card className="lg:col-span-2"><CardHeader title="Detected risks" />
          {isLoading ? <div className="p-5"><Skeleton className="h-40" /></div> : !data?.items.length ? <EmptyState title="No open risks" hint="Nothing in the chat currently looks risky." /> : (
            <ul className="divide-y">{data.items.map((r) => (
              <li key={r.id} className="px-5 py-3.5"><div className="flex items-start gap-3"><AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-500" />
                <div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><p className="text-sm font-medium">{r.title}</p><SeverityBadge severity={r.severity} /></div>
                  <p className="muted mt-0.5 text-sm">{r.description}</p>{r.recommendedAction && <p className="mt-1 text-sm"><span className="font-medium">Recommended:</span> {r.recommendedAction}</p>}
                  <p className="muted mt-1 text-xs">Based on {r.sourceMessageIds.length} message{r.sourceMessageIds.length === 1 ? '' : 's'}</p></div></div></li>))}</ul>)}
        </Card>
      </div>
      <Card className="mt-5"><CardHeader title={<span className="flex items-center gap-1.5"><Swords className="size-4" />Conflicting statements</span>} sub="Potential contradictions — never assumed to be anyone’s fault" />
        {conflicts.isLoading ? <div className="p-5"><Skeleton className="h-24" /></div> : !conflicts.data?.length ? <EmptyState title="No contradictions found" /> : (
          <ul className="divide-y">{conflicts.data.map((c) => (
            <li key={c.id} className="px-5 py-3.5"><div className="mb-2 flex items-center gap-2"><Badge tone="amber">Potential contradiction</Badge><span className="text-sm font-medium">Topic: {c.topic}</span><SeverityBadge severity={c.severity} /><StatusBadge status={c.status === 'NEEDS_VERIFICATION' ? 'OPEN' : c.status} /></div>
              <div className="grid gap-2 sm:grid-cols-2"><blockquote className="rounded-lg bg-[var(--surface-2)] p-3 text-sm"><span className="muted block text-xs">Statement A</span>{c.statementA}</blockquote>
                <blockquote className="rounded-lg bg-[var(--surface-2)] p-3 text-sm"><span className="muted block text-xs">Statement B</span>{c.statementB}</blockquote></div></li>))}</ul>)}
      </Card>
    </>
  );
}
