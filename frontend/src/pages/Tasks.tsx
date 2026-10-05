import { zodResolver } from '@hookform/resolvers/zod';
import { Plus, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { useOutletContext } from 'react-router-dom';
import { z } from 'zod';
import { EvidenceDrawer } from '../components/Evidence';
import { Badge, Button, Card, ConfidenceBadge, Dialog, EmptyState, ErrorState, Field, Input, PageHeader, Select, SeverityBadge, StatusBadge, TableSkeleton, Td, Th, useToast } from '../components/ui';
import { api, apiError } from '../lib/api';
import { useAuth } from '../lib/auth';
import { fmtDate, isOverdue } from '../lib/format';
import { useInvalidateProject, useTasks, useTeam, useUpdateTask } from '../lib/queries';
import type { Task } from '../lib/types';

const schema = z.object({
  title: z.string().min(1, 'Title is required').max(300), status: z.enum(['TODO', 'IN_PROGRESS', 'COMPLETED', 'BLOCKED', 'CANCELLED']),
  priority: z.enum(['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']), assigneeId: z.string().optional(), deadline: z.string().optional(),
  weight: z.coerce.number().min(0.5, 'Min 0.5').max(20, 'Max 20'),
});
type Form = z.infer<typeof schema>;

function TaskDialog({ projectId, task, open, onClose }: { projectId: string; task: Task | null; open: boolean; onClose: () => void }) {
  const { can } = useAuth();
  const full = can('task:edit');
  const { data: team } = useTeam(open ? projectId : undefined);
  const update = useUpdateTask();
  const invalidate = useInvalidateProject();
  const toast = useToast();
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Form>({ resolver: zodResolver(schema) as never,
    values: { title: task?.title ?? '', status: task?.status ?? 'TODO', priority: task?.priority ?? 'MEDIUM', assigneeId: task?.assignee?.id ?? '',
      deadline: task?.deadline ? task.deadline.slice(0, 10) : '', weight: task?.weight ?? 2 } });

  const submit = handleSubmit(async (v) => {
    const body: any = full ? { title: v.title, status: v.status, priority: v.priority, weight: v.weight, assigneeId: v.assigneeId || null,
      deadline: v.deadline ? new Date(v.deadline + 'T18:00:00Z').toISOString() : null } : { status: v.status };
    try {
      if (task) await update.mutateAsync({ id: task.id, body }); else { await api.post(`/projects/${projectId}/tasks`, body); invalidate(projectId); }
      toast.push('success', task ? 'Task updated — your correction is kept on re-analysis' : 'Task created'); onClose();
    } catch (e) { toast.push('error', apiError(e).message); }
  });
  return (
    <Dialog open={open} onClose={onClose} title={task ? 'Edit task' : 'New task'} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={isSubmitting} onClick={submit}>Save</Button></>}>
      <form className="space-y-3.5" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Field label="Title" error={errors.title?.message}><Input disabled={!full} {...register('title')} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Status"><Select {...register('status')}>{['TODO', 'IN_PROGRESS', 'COMPLETED', 'BLOCKED', 'CANCELLED'].map((s) => <option key={s} value={s}>{s.replace('_', ' ').toLowerCase()}</option>)}</Select></Field>
          <Field label="Priority"><Select disabled={!full} {...register('priority')}>{['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].map((s) => <option key={s} value={s}>{s.toLowerCase()}</option>)}</Select></Field>
          <Field label="Assignee"><Select disabled={!full} {...register('assigneeId')}><option value="">Unassigned</option>{team?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>
          <Field label="Deadline"><Input type="date" disabled={!full} {...register('deadline')} /></Field>
          <Field label="Weight (complexity)" error={errors.weight?.message}><Input type="number" step="0.5" disabled={!full} {...register('weight')} /></Field>
        </div>
        {!full && <p className="muted text-xs">You can update the status of tasks; other fields need a project manager.</p>}
      </form>
    </Dialog>
  );
}

export default function Tasks() {
  const { projectId } = useOutletContext<{ projectId?: string }>();
  const { can } = useAuth();
  const [status, setStatus] = useState(''); const [review, setReview] = useState(false); const [q, setQ] = useState('');
  const params: Record<string, string> = {}; if (status) params.status = status; if (review) params.needsReview = 'true';
  const { data, isLoading, error, refetch } = useTasks(projectId, params);
  const [edit, setEdit] = useState<Task | null | 'new'>(null);
  const [evidence, setEvidence] = useState<string | null>(null);
  const internal = can('analytics:view');
  const rows = useMemo(() => (data?.items ?? []).filter((t) => !q || t.title.toLowerCase().includes(q.toLowerCase()) || t.assignee?.name.toLowerCase().includes(q.toLowerCase())), [data, q]);
  if (!projectId) return <EmptyState title="Select a project first" />;
  return (
    <>
      <PageHeader title="Tasks" sub="Extracted from the conversation. Click a task to see the exact messages it came from."
        actions={can('task:edit') && <Button variant="primary" onClick={() => setEdit('new')}><Plus className="size-4" />New task</Button>} />
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b p-3">
          <div className="relative min-w-48 flex-1"><Search className="muted pointer-events-none absolute left-3 top-2.5 size-4" /><Input aria-label="Filter tasks" className="pl-9" placeholder="Filter by title or person…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
          <Select aria-label="Status" className="w-40" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option>{['TODO', 'IN_PROGRESS', 'COMPLETED', 'BLOCKED', 'CANCELLED'].map((s) => <option key={s} value={s}>{s.replace('_', ' ').toLowerCase()}</option>)}</Select>
          {internal && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={review} onChange={(e) => setReview(e.target.checked)} className="size-4 accent-[var(--color-brand-600)]" />Needs review</label>}
        </div>
        {isLoading ? <TableSkeleton rows={6} cols={6} /> : error ? <ErrorState error={error} onRetry={refetch} /> : !rows.length ? <EmptyState title="No tasks match" hint="Upload a chat to extract tasks automatically, or add one manually." /> : (
          <div className="overflow-x-auto"><table className="w-full min-w-[820px]"><thead className="border-b bg-[var(--surface-2)]/50"><tr><Th>Task</Th>{internal && <Th>Assignee</Th>}<Th>Status</Th>{internal && <Th>Priority</Th>}<Th>Deadline</Th>{internal && <Th>AI confidence</Th>}<Th /></tr></thead>
            <tbody className="divide-y">{rows.map((t) => (
              <tr key={t.id} className="cursor-pointer hover:bg-[var(--surface-2)]/50" onClick={() => internal ? setEvidence(t.id) : undefined}>
                <Td className="max-w-md"><p className="font-medium">{t.title}</p>{t.externalDependency && <p className="muted text-xs">Waiting on: {t.externalDependency}</p>}</Td>
                {internal && <Td>{t.assignee?.name ?? <span className="muted">Unassigned</span>}</Td>}
                <Td><StatusBadge status={t.status} /></Td>{internal && <Td>{t.priority && <SeverityBadge severity={t.priority} />}</Td>}
                <Td className={isOverdue(t.deadline, t.status) ? 'font-medium text-red-600 dark:text-red-400' : ''}>{fmtDate(t.deadline)}{isOverdue(t.deadline, t.status) && <Badge tone="red" className="ml-2">Overdue</Badge>}</Td>
                {internal && <Td>{t.reviewState?.startsWith('HUMAN') ? <Badge tone="blue">Human-verified</Badge> : <ConfidenceBadge value={t.confidence} needsReview={t.needsReview} />}</Td>}
                <Td onClick={(e) => e.stopPropagation()}>{(can('task:edit') || can('task:status')) && <Button size="sm" variant="ghost" onClick={() => setEdit(t)}>Edit</Button>}</Td></tr>))}</tbody></table></div>)}
      </Card>
      {edit !== null && <TaskDialog projectId={projectId} task={edit === 'new' ? null : edit} open onClose={() => setEdit(null)} />}
      <EvidenceDrawer taskId={evidence} onClose={() => setEvidence(null)} />
    </>
  );
}
