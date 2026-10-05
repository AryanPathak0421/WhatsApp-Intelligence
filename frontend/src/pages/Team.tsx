import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { Badge, Card, CardHeader, Drawer, EmptyState, ErrorState, PageHeader, ProgressBar, Select, TableSkeleton, Td, Th, useToast } from '../components/ui';
import { api, apiError } from '../lib/api';
import { useAuth } from '../lib/auth';
import { pct, titleCase } from '../lib/format';
import { useTasks, useTeam, useTeamPerf } from '../lib/queries';
import { StatusBadge } from '../components/ui';

const ROLES = ['PROJECT_MANAGER', 'DEVELOPER', 'FRONTEND_DEVELOPER', 'BACKEND_DEVELOPER', 'FULLSTACK_DEVELOPER', 'QA', 'DESIGNER', 'SALES', 'CLIENT', 'CLIENT_REPRESENTATIVE', 'ADMIN', 'OTHER'];

function PersonDrawer({ projectId, person, onClose }: { projectId: string; person: any | null; onClose: () => void }) {
  const { data: tasks } = useTasks(person ? projectId : undefined);
  const mine = (tasks?.items ?? []).filter((t) => t.assignee?.name === person?.person);
  return (
    <Drawer open={!!person} onClose={onClose} title={person?.person ?? ''} width="max-w-xl">
      {person && (
        <div className="space-y-5">
          <div className="card p-4">
            <div className="flex items-end justify-between"><div><p className="muted text-xs">Contribution score</p><p className="text-3xl font-semibold tabular-nums">{person.score ?? '—'}<span className="muted text-sm">/100</span></p></div>
              {person.low_sample && <Badge tone="amber">Low sample — fewer than 3 tasks</Badge>}</div>
            <p className="muted mt-2 text-xs">{person.info_only.note} (this person sent {person.info_only.message_count} messages).</p>
          </div>
          <div><h4 className="mb-2 text-sm font-semibold">How the score is made up</h4>
            <ul className="space-y-2">{Object.entries<any>(person.components).map(([k, c]) => (
              <li key={k}><div className="flex justify-between text-xs"><span className="font-medium">{titleCase(k)}</span><span className="muted">{c.contribution !== undefined ? `+${c.contribution}` : `×${c.multiplier}`}</span></div>
                {c.value !== undefined && k !== 'blocked_penalty' && <ProgressBar value={c.value * 100} />}<p className="muted mt-0.5 text-xs">{c.reason}</p></li>))}</ul></div>
          <div className="grid grid-cols-4 gap-2 text-center text-xs">{[['Assigned', person.assigned], ['Done', person.completed], ['Blocked', person.blocked], ['Overdue', person.overdue]].map(([l, v]) => <div key={l as string} className="card py-2"><p className="text-lg font-semibold">{v}</p><p className="muted">{l}</p></div>)}</div>
          <div className="grid grid-cols-3 gap-2 text-center text-xs">{[['Bugs fixed', person.bugs_fixed], ['Tests verified', person.tests_verified], ['Commitments kept', person.commitments_fulfilled]].map(([l, v]) => <div key={l as string} className="card py-2"><p className="text-lg font-semibold">{v}</p><p className="muted">{l}</p></div>)}</div>
          <div><h4 className="mb-2 text-sm font-semibold">Tasks</h4>{!mine.length ? <p className="muted text-xs">No tasks.</p> : <ul className="divide-y">{mine.map((t) => <li key={t.id} className="flex items-center justify-between gap-2 py-2 text-sm"><span className="min-w-0 truncate">{t.title}</span><StatusBadge status={t.status} /></li>)}</ul>}</div>
        </div>)}
    </Drawer>
  );
}

export default function Team() {
  const { projectId } = useOutletContext<{ projectId?: string }>();
  const { can } = useAuth();
  const { data: team, isLoading, error, refetch } = useTeam(projectId);
  const perf = useTeamPerf(projectId, can('analytics:view'));
  const [sel, setSel] = useState<any | null>(null);
  const qc = useQueryClient();
  const toast = useToast();
  if (!projectId) return <EmptyState title="Select a project first" />;
  const setRole = async (id: string, role: string) => {
    try { await api.put(`/projects/${projectId}/team/${id}`, { role }); await qc.invalidateQueries({ queryKey: ['team'] }); toast.push('success', 'Role updated — it will not be overwritten by re-analysis'); }
    catch (e) { toast.push('error', apiError(e).message); }
  };
  return (
    <>
      <PageHeader title="Team" sub="Everyone detected in the chat, with explainable contribution scores." />
      <Card className="overflow-hidden">
        <CardHeader title="Developer performance" sub="Score = completed weighted work, on-time delivery, bug fixes, deployments, commitments. Message count is not used." />
        {perf.isLoading ? <TableSkeleton /> : perf.error ? <ErrorState error={perf.error} onRetry={perf.refetch} /> : !perf.data?.developers.length ? <EmptyState title="No assigned work found yet" /> : (
          <div className="overflow-x-auto"><table className="w-full min-w-[760px]"><thead className="border-y bg-[var(--surface-2)]/50"><tr><Th>Developer</Th><Th>Assigned</Th><Th>Completed</Th><Th>Pending</Th><Th>Blocked</Th><Th>Overdue</Th><Th>Completion</Th><Th>On-time</Th><Th>Score</Th></tr></thead>
            <tbody className="divide-y">{perf.data.developers.map((d: any) => (
              <tr key={d.person} className="cursor-pointer hover:bg-[var(--surface-2)]/50" onClick={() => setSel(d)}>
                <Td className="font-medium">{d.person}{d.low_sample && <Badge tone="amber" className="ml-2">low sample</Badge>}</Td><Td>{d.assigned}</Td><Td>{d.completed}</Td><Td>{d.pending + d.in_progress}</Td><Td>{d.blocked}</Td>
                <Td className={d.overdue ? 'font-medium text-red-600 dark:text-red-400' : ''}>{d.overdue}</Td><Td>{pct(d.completion_pct)}</Td><Td>{pct(d.on_time_pct)}</Td>
                <Td><div className="flex items-center gap-2"><div className="w-16"><ProgressBar value={d.score} /></div><span className="font-semibold tabular-nums">{d.score ?? '—'}</span></div></Td></tr>))}</tbody></table></div>)}
      </Card>
      <Card className="mt-5 overflow-hidden">
        <CardHeader title="Chat participants" sub="Roles are inferred automatically — correct them and the fix sticks." />
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : !team?.length ? <EmptyState title="No participants yet" hint="Upload a chat to identify the team." /> : (
          <div className="overflow-x-auto"><table className="w-full min-w-[640px]"><thead className="border-y bg-[var(--surface-2)]/50"><tr><Th>Name</Th><Th>Role</Th><Th>Source</Th><Th>Messages</Th><Th>Tasks</Th><Th>Phone</Th></tr></thead>
            <tbody className="divide-y">{team.map((p) => (
              <tr key={p.id}><Td className="font-medium">{p.name}</Td>
                <Td>{can('team:edit') ? <Select aria-label={`Role for ${p.name}`} className="h-8 w-52" value={p.role} onChange={(e) => setRole(p.id, e.target.value)}>{ROLES.map((r) => <option key={r} value={r}>{titleCase(r)}</option>)}</Select> : titleCase(p.role)}</Td>
                <Td><Badge tone={p.roleSource === 'admin' ? 'blue' : 'gray'}>{p.roleSource === 'admin' ? 'set manually' : `auto (${Math.round((p.roleConfidence ?? 0) * 100)}%)`}</Badge></Td>
                <Td>{p.messageCount}</Td><Td>{p.taskCount}</Td><Td className="muted tabular-nums">{p.phone ?? '—'}</Td></tr>))}</tbody></table></div>)}
      </Card>
      <PersonDrawer projectId={projectId} person={sel} onClose={() => setSel(null)} />
    </>
  );
}
