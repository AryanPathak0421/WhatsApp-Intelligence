import { AlertOctagon, FolderKanban, Gauge, Hourglass, Users2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { SimpleBars } from '../components/charts';
import ChatUploadCard from '../components/ChatUploadCard';
import { Badge, Card, CardHeader, EmptyState, ErrorState, Kpi, PageHeader, ProgressBar, SeverityBadge, Skeleton, StatusBadge, Td, Th } from '../components/ui';
import { fmtDate, pct } from '../lib/format';
import { isShaky } from '../lib/types';
import { useExecutive } from '../lib/queries';

export default function Executive() {
  const { data, isLoading, error, refetch } = useExecutive();
  if (error) return <ErrorState error={error} onRetry={refetch} />;
  const t = data?.totals;
  return (
    <>
      <PageHeader title="Executive dashboard" sub="All projects you have access to, at a glance." />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {isLoading ? Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-24" />) : <>
          <Kpi label="Total projects" value={t.projects} sub={`${t.active} active`} icon={<FolderKanban className="size-4" />} />
          <Kpi label="At risk / critical" value={`${t.atRisk} / ${t.critical}`} sub={t.lowConfidence ? `${t.lowConfidence} low-confidence project${t.lowConfidence === 1 ? '' : 's'} not counted` : undefined} tone={t.critical ? 'bad' : t.atRisk ? 'warn' : 'ok'} icon={<AlertOctagon className="size-4" />} />
          <Kpi label="Average progress" value={pct(t.averageProgress, 1)} icon={<Gauge className="size-4" />} />
          <Kpi label="Team engaged" value={t.teamUtilization === null ? '—' : `${t.teamUtilization}%`} sub="people with open work" icon={<Users2 className="size-4" />} />
          <Kpi label="Client pending items" value={t.clientPending} tone={t.clientPending > 5 ? 'warn' : undefined} icon={<Hourglass className="size-4" />} />
          <Kpi label="Overdue tasks" value={t.overdue} tone={t.overdue ? 'bad' : 'ok'} />
          <Kpi label="Blockers" value={t.blockers} tone={t.blockers ? 'warn' : 'ok'} />
          <Kpi label="Open high risks" value={data.topRisks.length} tone={data.topRisks.length ? 'bad' : 'ok'} /></>}
      </div>

      <ChatUploadCard />

      <Card className="mt-5 overflow-hidden">
        <CardHeader title="Project comparison" sub="Spot problem projects quickly — progress and health come from the latest analysis." />
        {isLoading ? <div className="p-5"><Skeleton className="h-32" /></div> : !data.projects.length ? <EmptyState title="No projects yet" hint="Create a project and upload a WhatsApp export to get started." action={<Link to="/projects" className="text-sm text-brand-600 hover:underline">Go to projects</Link>} /> : (
          <div className="overflow-x-auto"><table className="w-full min-w-[820px]"><thead className="border-b bg-[var(--surface-2)]/50"><tr>
            <Th>Project</Th><Th>Client</Th><Th className="w-48">Progress</Th><Th>Health</Th><Th>Client pending</Th><Th>Overdue</Th><Th>Blocked</Th><Th>Open bugs</Th><Th>Due</Th></tr></thead>
            <tbody className="divide-y">{data.projects.map((p: any) => (
              <tr key={p.id} className="hover:bg-[var(--surface-2)]/50">
                <Td><Link className="font-medium text-brand-600 hover:underline" to={`/p/${p.id}/overview`}>{p.name}</Link></Td>
                <Td className="muted">{p.client ?? '—'}</Td>
                <Td>{p.progress === null ? <span className="muted text-xs">Not analysed</span> : <div className="flex min-w-28 items-center gap-2"><div className="min-w-16 flex-1"><ProgressBar value={p.progress} tone={p.progress >= 70 ? 'green' : p.progress >= 40 ? 'brand' : 'amber'} /></div><span className="w-10 text-xs tabular-nums">{pct(p.progress)}</span></div>}</Td>
                <Td>{p.health ? <div className="flex items-center gap-2"><span className="tabular-nums">{p.health.score}</span>{isShaky(p.reliability) ? <Badge tone="amber" title="Few or low-confidence tasks: this score is only indicative">Low confidence</Badge> : <StatusBadge status={p.health.status} />}</div> : '—'}</Td>
                <Td>{p.openClientPending}</Td><Td className={p.overdue ? 'font-medium text-red-600 dark:text-red-400' : ''}>{p.overdue}</Td><Td>{p.blocked}</Td><Td>{p.openBugs}</Td><Td className="muted">{fmtDate(p.expectedDelivery)}</Td>
              </tr>))}</tbody></table></div>)}
      </Card>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Card><CardHeader title="Top risks across projects" />
          {isLoading ? <div className="p-5"><Skeleton className="h-32" /></div> : !data.topRisks.length ? <EmptyState title="No high risks detected" hint="Nothing is flagged HIGH or CRITICAL right now." /> : (
            <ul className="divide-y">{data.topRisks.map((r: any) => (
              <li key={r.id} className="flex items-start gap-3 px-5 py-3"><SeverityBadge severity={r.severity} />
                <div className="min-w-0"><p className="text-sm font-medium">{r.title}</p><p className="muted text-xs"><Link className="hover:underline" to={`/p/${r.project.id}/risks`}>{r.project.name}</Link>{r.recommendedAction && ` · ${r.recommendedAction}`}</p></div></li>))}</ul>)}
        </Card>
        <Card><CardHeader title="Open work by project" sub="Where the pressure is" />
          <div className="px-3 pb-4">{isLoading ? <Skeleton className="h-52" /> : <SimpleBars data={data.projects} x="name" layout="vertical" height={Math.max(200, data.projects.length * 46)}
            bars={[{ key: 'openClientPending', name: 'Client pending', color: '#f59e0b', stack: 'a' }, { key: 'overdue', name: 'Overdue', color: '#ef4444', stack: 'a' }, { key: 'blocked', name: 'Blocked', color: '#8b5cf6', stack: 'a' }]} />}</div></Card>
      </div>
    </>
  );
}
