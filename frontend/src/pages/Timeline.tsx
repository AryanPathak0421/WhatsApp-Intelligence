import clsx from 'clsx';
import { useOutletContext } from 'react-router-dom';
import { Card, EmptyState, ErrorState, PageHeader, Skeleton } from '../components/ui';
import { fmtDate, fmtTime } from '../lib/format';
import { useTimeline } from '../lib/queries';

const DOT: Record<string, string> = { START: 'bg-slate-400', TASK_CREATED: 'bg-blue-500', COMPLETED: 'bg-emerald-500', DEPLOYMENT: 'bg-emerald-600', CLIENT_PENDING: 'bg-amber-500',
  CLIENT_RESOLVED: 'bg-teal-500', DECISION: 'bg-violet-500', REQUIREMENT_CHANGE: 'bg-red-500', MEETING: 'bg-sky-500' };

export default function Timeline() {
  const { projectId } = useOutletContext<{ projectId?: string }>();
  const { data, isLoading, error, refetch } = useTimeline(projectId);
  if (!projectId) return <EmptyState title="Select a project first" />;
  const days = (data ?? []).reduce<Record<string, any[]>>((m, e) => { (m[fmtDate(e.occurredAt)] ??= []).push(e); return m; }, {});
  return (
    <>
      <PageHeader title="Project timeline" sub="Built from what actually happened in the chat." />
      <Card className="p-5">
        {isLoading ? <Skeleton className="h-64" /> : error ? <ErrorState error={error} onRetry={refetch} /> : !data?.length ? <EmptyState title="No events yet" hint="Upload a chat to generate the timeline." /> : (
          <ol className="relative space-y-6 border-l pl-6">{Object.entries(days).map(([day, evs]) => (
            <li key={day}><span className="absolute -left-[5px] mt-1.5 size-2.5 rounded-full bg-[var(--border)]" /><p className="mb-2 text-sm font-semibold">{day}</p>
              <ul className="space-y-2">{evs.map((e) => <li key={e.id} className="flex items-start gap-2.5 text-sm"><span className={clsx('mt-1.5 size-2 shrink-0 rounded-full', DOT[e.type] ?? 'bg-slate-400')} /><span className="muted w-12 shrink-0 text-xs tabular-nums pt-0.5">{fmtTime(e.occurredAt)}</span><span>{e.title}</span></li>)}</ul></li>))}</ol>)}
      </Card>
    </>
  );
}
