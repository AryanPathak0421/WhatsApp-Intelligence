import { AlertTriangle, Bug, CheckCircle2, CircleDashed, Clock3, Gauge, HelpCircle, Hourglass, OctagonAlert, Sparkles } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link, useOutletContext } from 'react-router-dom';
import { COLORS, Donut, SimpleBars, Trend } from '../components/charts';
import { Badge, Button, Card, CardHeader, Drawer, EmptyState, ErrorState, Kpi, PageHeader, ProgressBar, SeverityBadge, Skeleton, StatusBadge } from '../components/ui';
import { useAuth } from '../lib/auth';
import { fmtDate, fmtShort, pct, titleCase } from '../lib/format';
import { useClientPending, useInsights, useOverview, useProgress, useSummary, useTeamPerf, useVelocity } from '../lib/queries';

const AREAS: [string, string][] = [['development', 'Development'], ['design', 'Design'], ['testing', 'Testing'], ['deployment', 'Deployment'], ['clientApproval', 'Client approval'], ['documentation', 'Documentation']];
const healthTone = (s?: string) => (s === 'HEALTHY' ? 'green' : s === 'AT_RISK' ? 'amber' : 'red');

function WhyDrawer({ projectId, open, onClose }: { projectId: string; open: boolean; onClose: () => void }) {
  const { data, isLoading } = useProgress(open ? projectId : undefined, true);
  const ex = data?.explanation;
  return (
    <Drawer open={open} onClose={onClose} title={`Why ${data?.overall ?? ''}%?`} width="max-w-2xl">
      {isLoading && <Skeleton className="h-40" />}
      {data && !ex && <EmptyState title="Detail not available" hint="Task-level detail is only shown to internal team members." />}
      {ex && (
        <div className="space-y-5 text-sm">
          <div className="card p-4"><p className="font-medium">{data.overall}% = {ex.completed_weight} of {ex.total_weight} weighted work completed</p>
            <p className="muted mt-1 text-xs">{ex.formula}. Counts: {Object.entries(ex.task_counts).map(([k, v]) => `${v} ${titleCase(k).toLowerCase()}`).join(', ')}.</p>
            <p className="muted mt-1 text-xs">Reliability {Math.round(ex.reliability * 100)}% (share of tasks the AI is confident about).</p>
            {ex.warnings.map((w: string) => <p key={w} className="mt-2 flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-300"><AlertTriangle className="mt-0.5 size-3.5 shrink-0" />{w}</p>)}</div>
          <div><h4 className="mb-2 font-semibold">Holding progress back</h4>
            {!ex.holding_back.length ? <p className="muted text-xs">Nothing — every task is complete.</p> : <ul className="space-y-1.5">{ex.holding_back.map((t: any) => (
              <li key={t.task_id} className="flex items-center justify-between gap-3 rounded-lg bg-[var(--surface-2)] px-3 py-2"><span className="min-w-0 truncate">{t.title}</span>
                <span className="flex shrink-0 items-center gap-2"><span className="muted text-xs">weight {t.weight} · {t.share_of_project_pct}% of project</span><StatusBadge status={t.status} /></span></li>))}</ul>}</div>
          <div><h4 className="mb-2 font-semibold">Task contributions</h4>
            <table className="w-full text-xs"><thead><tr className="muted text-left"><th className="py-1">Task</th><th>Weight</th><th>Credit</th><th>Points</th></tr></thead>
              <tbody className="divide-y">{ex.task_contributions.map((t: any) => <tr key={t.task_id}><td className="py-1.5 pr-2">{t.title}</td><td>{t.weight}</td><td>{t.credit}</td><td className="font-medium">{t.points}</td></tr>)}</tbody></table></div>
        </div>
      )}
    </Drawer>
  );
}

export default function ProjectDashboard() {
  const { projectId } = useOutletContext<{ projectId?: string }>();
  const { can } = useAuth();
  const internal = can('analytics:view');
  const { data: o, isLoading, error, refetch } = useOverview(projectId);
  const summary = useSummary(projectId);
  const actions = useInsights(projectId, 'NEXT_ACTION', internal);
  const perf = useTeamPerf(projectId, internal && can('team:view'));
  const vel = useVelocity(projectId, internal);
  const cp = useClientPending(projectId, { status: 'OPEN' });
  const [why, setWhy] = useState(false);

  const cpByType = useMemo(() => {
    const m: Record<string, number> = {};
    (cp.data ?? []).forEach((c) => { m[c.type] = (m[c.type] ?? 0) + 1; });
    return Object.entries(m).map(([type, count]) => ({ type: titleCase(type), count }));
  }, [cp.data]);

  if (!projectId) return <EmptyState title="No project selected" hint="Create or select a project to see its dashboard." action={<Link className="text-sm text-brand-600 hover:underline" to="/projects">Go to projects</Link>} />;
  if (error) return <ErrorState error={error} onRetry={refetch} />;
  if (isLoading || !o) return <div className="space-y-4"><Skeleton className="h-32" /><div className="grid grid-cols-2 gap-3 md:grid-cols-4">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-24" />)}</div></div>;

  const t = o.tasks, pending = t.TODO + t.IN_PROGRESS;
  const analysed = !!o.progress;
  const tone = healthTone(o.health?.status);
  const contrib = (perf.data?.developers ?? []).filter((d: any) => d.score !== null).map((d: any) => ({ name: d.person.split(' ')[0], score: d.score, completed: d.completed, assigned: d.assigned }));
  const weeks = (vel.data?.velocity?.weeks ?? []).map((w: any) => ({ week: fmtShort(w.week_ending), tasks: w.tasks, weight: w.weight }));
  const tl = (vel.data?.timeline ?? []).filter((r: any) => r.progress !== null).map((r: any) => ({ date: fmtShort(r.date), progress: r.progress }));
  const messagesPerDay = Object.entries<number>(perf.data?.communication?.messages_per_day ?? {}).map(([d, n]) => ({ date: fmtShort(d), messages: n }));

  return (
    <>
      <PageHeader title={o.project.name} sub={<span className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span>Client: <b className="font-medium text-[var(--text)]">{o.project.client ?? '—'}</b></span><span>PM: <b className="font-medium text-[var(--text)]">{o.project.manager?.name ?? '—'}</b></span>
        <span>Start: {fmtDate(o.project.startDate)}</span><span>Delivery: {fmtDate(o.project.expectedDelivery)}</span><StatusBadge status={o.project.status} /></span>}
        actions={internal && analysed && <Button onClick={() => setWhy(true)}><HelpCircle className="size-4" />Why {Math.round(o.progress!.overall)}%?</Button>} />

      {!analysed ? (
        <Card><EmptyState icon={<CircleDashed className="size-5" />} title="This project hasn’t been analysed yet"
          hint={o.lastAnalysis && o.lastAnalysis.status !== 'COMPLETED' ? `Analysis ${o.lastAnalysis.status.toLowerCase()} — ${o.lastAnalysis.stage ?? ''}` : 'Upload a WhatsApp chat export to see progress, health, risks and more.'}
          action={can('chat:upload') && <Link to={`/p/${projectId}/chat`}><Button variant="primary">Upload a chat</Button></Link>} /></Card>
      ) : (<>
        <Card className="overflow-hidden">
          <div className="grid gap-6 p-5 md:grid-cols-[260px_1fr]">
            <div>
              <p className="muted text-xs font-medium uppercase tracking-wide">Project health</p>
              <div className="mt-2 flex items-end gap-3"><span className="text-5xl font-semibold tabular-nums">{Math.round(o.progress!.overall)}%</span>
                <Badge tone={tone as any} className="mb-2 text-xs">{titleCase(o.health?.status ?? 'unknown')}</Badge></div>
              <p className="muted mt-1 text-xs">Overall completion · health score {o.health?.score}/100</p>
              <ProgressBar value={o.progress!.overall} height={10} tone={tone === 'green' ? 'green' : tone === 'amber' ? 'amber' : 'red'} label="Overall progress" />
            </div>
            <div className="grid content-center gap-x-8 gap-y-3 sm:grid-cols-2">
              {AREAS.map(([k, label]) => {
                const v = (o.progress as any)[k] as number | null;
                return <div key={k}><div className="mb-1 flex justify-between text-xs"><span className="font-medium">{label}</span><span className="muted tabular-nums">{v === null ? 'no data' : pct(v)}</span></div>
                  <ProgressBar value={v} label={label} tone={v !== null && v >= 70 ? 'green' : v !== null && v < 40 ? 'amber' : 'brand'} /></div>;
              })}
            </div>
          </div>
        </Card>

        <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Kpi label="Project progress" value={pct(o.progress!.overall)} icon={<Gauge className="size-4" />} />
          <Kpi label="Health score" value={`${o.health?.score}/100`} tone={tone === 'green' ? 'ok' : tone === 'amber' ? 'warn' : 'bad'} />
          <Kpi label="Completed tasks" value={t.COMPLETED} icon={<CheckCircle2 className="size-4" />} />
          <Kpi label="Pending tasks" value={pending} sub={`${t.IN_PROGRESS} in progress`} icon={<Clock3 className="size-4" />} />
          <Kpi label="Blocked tasks" value={t.BLOCKED} tone={t.BLOCKED ? 'warn' : 'ok'} icon={<OctagonAlert className="size-4" />} />
          <Kpi label="Client pending" value={o.clientPendingOpen} tone={o.clientPendingOpen > 4 ? 'warn' : undefined} icon={<Hourglass className="size-4" />} />
          <Kpi label="Overdue" value={o.overdue} tone={o.overdue ? 'bad' : 'ok'} />
          {internal ? <Kpi label="Open bugs" value={o.openBugs ?? 0} tone={(o.openBugs ?? 0) > 4 ? 'warn' : undefined} icon={<Bug className="size-4" />} /> : <Kpi label="Messages analysed" value={o.messages} />}
        </div>

        <div className="mt-5 grid gap-5 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader title={<span className="flex items-center gap-1.5"><Sparkles className="size-4 text-brand-500" />Executive summary</span>} sub="Written from structured evidence — nothing is invented" />
            <div className="px-5 pb-5">{summary.isLoading ? <Skeleton className="h-24" /> : summary.data?.claims ? (
              <ul className="space-y-2 text-sm">{summary.data.claims.map((c, i) => <li key={i} className="flex gap-2"><span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-brand-500" />{c.text}</li>)}</ul>
            ) : <p className="text-sm">{summary.data?.text}</p>}</div>
          </Card>
          {internal && <Card>
            <CardHeader title="Next actions" sub="From unresolved dependencies" />
            {actions.isLoading ? <div className="p-5"><Skeleton className="h-24" /></div> : !actions.data?.length ? <EmptyState title="Nothing urgent" /> : (
              <ul className="divide-y">{actions.data.slice(0, 5).map((a: any) => (
                <li key={a.id} className="px-5 py-3"><div className="flex items-center gap-2">{a.priority && <SeverityBadge severity={a.priority} />}<span className="muted text-xs">{a.owner ?? 'Unassigned'}</span></div><p className="mt-1 text-sm">{a.text}</p></li>))}</ul>)}
          </Card>}
        </div>

        <div className="mt-5 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          <Card><CardHeader title="Task status" /><div className="px-3 pb-4"><Donut data={(['COMPLETED', 'IN_PROGRESS', 'TODO', 'BLOCKED'] as const).map((s) => ({ name: titleCase(s), value: t[s], color: COLORS[s] }))} /></div></Card>
          {internal && <Card><CardHeader title="Progress over time" sub="Weighted completion, by day" /><div className="px-3 pb-4">{tl.length > 1 ? <Trend data={tl} x="date" unit="%" lines={[{ key: 'progress', color: COLORS.brand, name: 'Progress' }]} /> : <EmptyState title="Not enough history yet" />}</div></Card>}
          {internal && <Card><CardHeader title="Velocity" sub="Weighted work completed per week" /><div className="px-3 pb-4">{weeks.length ? <SimpleBars data={weeks} x="week" bars={[{ key: 'weight', name: 'Weight', color: COLORS.brand }, { key: 'tasks', name: 'Tasks', color: '#94a3b8' }]} /> : <EmptyState title="No completions yet" />}</div></Card>}
          {internal && <Card><CardHeader title="Developer contribution" sub="Explainable score — not message count" /><div className="px-3 pb-4">{contrib.length ? <SimpleBars data={contrib} x="name" layout="vertical" height={Math.max(180, contrib.length * 44)} bars={[{ key: 'score', name: 'Score', color: COLORS.brand }]} /> : <EmptyState title="No contribution data" />}</div></Card>}
          <Card><CardHeader title="Client pending by type" /><div className="px-3 pb-4">{cpByType.length ? <SimpleBars data={cpByType} x="type" bars={[{ key: 'count', name: 'Open items', color: '#f59e0b' }]} /> : <EmptyState title="Nothing waiting on the client" />}</div></Card>
          {internal && o.risksBySeverity && <Card><CardHeader title="Risk distribution" /><div className="px-3 pb-4"><SimpleBars data={(['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'] as const).map((s) => ({ severity: titleCase(s), count: o.risksBySeverity![s] }))} x="severity" bars={[{ key: 'count', name: 'Risks', color: '#ef4444' }]} /></div></Card>}
          {internal && messagesPerDay.length > 1 && <Card className="xl:col-span-3"><CardHeader title="Chat activity" sub="Messages per day (volume is not performance)" /><div className="px-3 pb-4"><SimpleBars data={messagesPerDay} x="date" height={180} bars={[{ key: 'messages', name: 'Messages', color: '#94a3b8' }]} /></div></Card>}
        </div>
      </>)}
      <WhyDrawer projectId={projectId} open={why} onClose={() => setWhy(false)} />
    </>
  );
}
