import { useOutletContext } from 'react-router-dom';
import { COLORS, SimpleBars, Trend } from '../components/charts';
import { Card, CardHeader, EmptyState, ErrorState, Kpi, PageHeader, Skeleton } from '../components/ui';
import { fmtShort } from '../lib/format';
import { useResponseTime, useTeamPerf, useVelocity } from '../lib/queries';

const hrs = (h?: number) => (h === undefined || h === null ? '—' : h < 1 ? `${Math.round(h * 60)} min` : `${h.toFixed(1)} h`);

export default function Analytics() {
  const { projectId } = useOutletContext<{ projectId?: string }>();
  const vel = useVelocity(projectId);
  const perf = useTeamPerf(projectId);
  const rt = useResponseTime(projectId);
  if (!projectId) return <EmptyState title="Select a project first" />;
  if (vel.error) return <ErrorState error={vel.error} onRetry={vel.refetch} />;
  const weeks = (vel.data?.velocity?.weeks ?? []).map((w: any) => ({ week: fmtShort(w.week_ending), tasks: w.tasks, weight: w.weight }));
  const daily = (vel.data?.timeline ?? []).map((r: any) => ({ date: fmtShort(r.date), progress: r.progress, delta: r.delta }));
  const msgs = Object.entries<number>(perf.data?.communication?.messages_per_day ?? {}).map(([d, n]) => ({ date: fmtShort(d), messages: n }));
  const comm = perf.data?.communication;
  const people = Object.keys({ ...(comm?.tasks_received ?? {}), ...(comm?.tasks_resolved ?? {}) }).map((p) => ({
    name: p.split(' ')[0], received: comm.tasks_received[p] ?? 0, resolved: comm.tasks_resolved?.[p] ?? 0, overdue: comm.overdue_by_person?.[p] ?? 0 }));
  const r = rt.data;
  return (
    <>
      <PageHeader title="Analytics" sub="Trends computed from the analysed conversation." />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {rt.isLoading ? Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-24" />) : <>
          <Kpi label="Avg client response" value={hrs(r?.avg_hours)} sub={r?.pairs ? `${r.pairs} request/reply pairs` : 'No pairs found'} />
          <Kpi label="Slowest response" value={hrs(r?.max_hours)} />
          <Kpi label="Fastest response" value={hrs(r?.min_hours)} />
          <Kpi label="Client silent for" value={r?.client_inactive_days === null || r?.client_inactive_days === undefined ? '—' : `${r.client_inactive_days} d`} tone={r?.client_inactive_days > 4 ? 'warn' : undefined} /></>}
      </div>
      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Card><CardHeader title="Weekly velocity" sub="Weighted work completed per week" /><div className="px-3 pb-4">
          {vel.isLoading ? <Skeleton className="h-52" /> : weeks.length ? <SimpleBars data={weeks} x="week" bars={[{ key: 'weight', name: 'Weight', color: COLORS.brand }, { key: 'tasks', name: 'Tasks', color: '#94a3b8' }]} /> : <EmptyState title="No completed work yet" />}</div></Card>
        <Card><CardHeader title="Progress by day" /><div className="px-3 pb-4">
          {daily.length > 1 ? <Trend data={daily} x="date" unit="%" lines={[{ key: 'progress', color: COLORS.brand, name: 'Progress' }]} /> : <EmptyState title="Not enough history" />}</div></Card>
        <Card><CardHeader title="Communication volume" sub="Messages per day — not a performance measure" /><div className="px-3 pb-4">
          {msgs.length ? <SimpleBars data={msgs} x="date" bars={[{ key: 'messages', name: 'Messages', color: '#94a3b8' }]} /> : <EmptyState title="No data" />}</div></Card>
        <Card><CardHeader title="Workload by person" sub="Tasks received, resolved and overdue" /><div className="px-3 pb-4">
          {people.length ? <SimpleBars data={people} x="name" bars={[{ key: 'received', name: 'Received', color: '#94a3b8' }, { key: 'resolved', name: 'Resolved', color: '#16a34a' }, { key: 'overdue', name: 'Overdue', color: '#ef4444' }]} /> : <EmptyState title="No assignments found" />}</div></Card>
      </div>
    </>
  );
}
